"""DownVideo: local API and authenticated personal deployment behind HTTPS."""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

import deployment as config

ROOT = Path(__file__).resolve().parent
DATA = config.STATE
JOBS = DATA / 'jobs'
DOWNLOADS = config.DOWNLOADS
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
STOP = threading.Event()
PROCESSES: dict[str, subprocess.Popen] = {}
MAX_ACTIVE = config.MAX_ACTIVE
ID_PATTERN = re.compile(r'^[a-f0-9]{32}$')
PUBLIC_FIELDS = ('id', 'url', 'status', 'created_at', 'updated_at', 'title', 'uploader',
                 'source', 'thumbnail', 'duration', 'formats', 'progress', 'speed', 'eta',
                 'error', 'filename', 'size', 'selection', 'quality', 'fps', 'container',
                 'actual_height', 'actual_fps', 'has_audio', 'downloaded_bytes', 'total_bytes')


class UserError(Exception):
    pass


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'.{secrets.token_hex(4)}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            time.sleep(.03 * (attempt + 1))
    temporary.unlink(missing_ok=True)
    raise OSError('Không thể lưu trạng thái tải.')


def read_job(job_id: str) -> dict:
    if not ID_PATTERN.fullmatch(job_id):
        raise UserError('Mã video không hợp lệ.')
    try:
        return json.loads((JOBS / f'{job_id}.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise UserError('Không tìm thấy video này.') from None


def public_job(job: dict) -> dict:
    return {key: job[key] for key in PUBLIC_FIELDS if key in job}


def validate_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise UserError('Vui lòng nhập một link video hợp lệ.')
    value = value.strip()
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise UserError('Link video không hợp lệ.') from None
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise UserError('Chỉ chấp nhận link http:// hoặc https:// công khai.')
    if any(ord(char) < 32 for char in value) or port not in (None, 80, 443):
        raise UserError('Link chứa ký tự hoặc cổng không được hỗ trợ.')
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UserError('Không tìm thấy tên miền. Hãy kiểm tra link và kết nối Internet.') from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise UserError('Vui lòng dùng link Internet công khai, không dùng địa chỉ mạng nội bộ.')
    return value


def all_jobs() -> list[dict]:
    result = []
    for path in JOBS.glob('*.json'):
        try:
            result.append(public_job(json.loads(path.read_text(encoding='utf-8'))))
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda item: item['created_at'], reverse=True)


def launch(job: dict, action: str):
    active = [p for p in PROCESSES.values() if p.poll() is None]
    if len(active) >= MAX_ACTIVE:
        job.update(status='queued_analyze' if action == 'analyze' else 'queued_download', pending_action=action)
        write_json(JOBS / f"{job['id']}.json", job)
        return
    job.pop('pending_action', None)
    job['status'] = 'analyzing' if action == 'analyze' else 'downloading'
    job['started_at'] = time.time()
    write_json(JOBS / f"{job['id']}.json", job)
    log = (DATA / 'worker.log').open('ab')
    try:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'downloader.py'), action, job['id']],
            cwd=str(ROOT), stdout=log, stderr=log,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            start_new_session=os.name != 'nt',
        )
        PROCESSES[job['id']] = process
    finally:
        log.close()


def schedule_jobs():
    last_cleanup = 0
    while not STOP.wait(.5):
        with LOCK:
            if STOP.is_set():
                break
            now = time.time()
            for job_id, process in list(PROCESSES.items()):
                if process.poll() is None:
                    job = read_job(job_id)
                    if now - job.get('started_at', now) > config.MAX_JOB_SECONDS:
                        stop_worker(process)
                        job.update(status='error', error='Tác vụ vượt thời gian cho phép. Hãy thử video ngắn hơn.', updated_at=now)
                        write_json(JOBS / f'{job_id}.json', job)
            if config.RETENTION_HOURS and now - last_cleanup > 60:
                cleanup_expired(now)
                last_cleanup = now
            for job in reversed(all_jobs()):
                if job['status'] in ('queued_analyze', 'queued_download'):
                    if sum(process.poll() is None for process in PROCESSES.values()) >= MAX_ACTIVE:
                        break
                    full = read_job(job['id'])
                    launch(full, full['pending_action'])


def stop_worker(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def cleanup_expired(now):
    """Prune only app-generated directories under the configured public data root."""
    for summary in all_jobs():
        job = read_job(summary['id'])
        if job['status'] in ('analyzing', 'downloading', 'processing', 'queued_analyze', 'queued_download'):
            continue
        if now - job.get('updated_at', job['created_at']) <= config.RETENTION_HOURS * 3600:
            continue
        folder = (DOWNLOADS / job['id']).resolve()
        if folder.parent == DOWNLOADS.resolve() and ID_PATTERN.fullmatch(folder.name) and folder.is_dir():
            shutil.rmtree(folder)
        (JOBS / f"{job['id']}.json").unlink(missing_ok=True)
    # Hidden history records can leave their generated download folder behind.
    for folder in DOWNLOADS.iterdir():
        if folder.is_dir() and not folder.is_symlink() and ID_PATTERN.fullmatch(folder.name) and not (JOBS / f'{folder.name}.json').exists():
            if now - folder.stat().st_mtime > config.RETENTION_HOURS * 3600 and folder.resolve().parent == DOWNLOADS.resolve():
                shutil.rmtree(folder)


def check_capacity():
    queued = sum(job['status'] in ('analyzing', 'downloading', 'processing', 'queued_analyze', 'queued_download') for job in all_jobs())
    if queued >= config.MAX_QUEUE:
        raise UserError('Hàng đợi đã đầy. Hãy đợi một số tác vụ hoàn tất.')
    if config.MAX_STORAGE_BYTES and config.storage_usage() >= config.MAX_STORAGE_BYTES:
        raise UserError('Bộ nhớ máy chủ đang đầy. Hãy đợi các tệp cũ hết hạn lưu trữ.')
    if config.PUBLIC and shutil.disk_usage(DOWNLOADS).free < 512 * 1024 * 1024:
        raise UserError('Máy chủ không còn đủ dung lượng trống để tải video.')


class Handler(BaseHTTPRequestHandler):
    server_version = 'DownVideo/1.0'

    def log_message(self, fmt, *args):
        # Do not log submitted URLs or query parameters.
        if not self.path.startswith('/api/'):
            super().log_message(fmt, *args)

    def safe_host(self):
        try:
            hostname = urlsplit('http://' + self.headers.get('Host', '')).hostname
            return hostname in ('127.0.0.1', 'localhost', '::1') or (config.PUBLIC and hostname == config.public_hostname())
        except ValueError:
            return False

    def authorized(self):
        if not config.PUBLIC:
            return True
        try:
            scheme, encoded = self.headers.get('Authorization', '').split(' ', 1)
            if scheme.lower() != 'basic':
                raise ValueError()
            supplied = base64.b64decode(encoded, validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            supplied = ''
        expected = config.ACCESS_USER + ':' + config.ACCESS_PASSWORD
        if secrets.compare_digest(hashlib.sha256(supplied.encode()).digest(), hashlib.sha256(expected.encode()).digest()):
            return True
        payload = b'Authentication required.'
        self.send_response(401)
        self.send_common()
        self.send_header('WWW-Authenticate', 'Basic realm="DownVideo", charset="UTF-8"')
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        return False

    def send_common(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cache-Control', 'no-store')
        if config.PUBLIC:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')

    def json_response(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self.safe_host():
            return self.json_response({'error': 'Chỉ truy cập qua localhost.'}, 403)
        path = unquote(urlsplit(self.path).path)
        if path == '/healthz':
            return self.json_response({'status': 'ok'})
        if not self.authorized():
            return
        if path == '/api/config':
            return self.json_response({
                'token': TOKEN, 'engine_ready': config.engine_ready(),
                'ffmpeg_ready': bool(config.ffmpeg_path()),
                'runtime_ready': bool(config.deno_path()), 'hosted': config.PUBLIC,
                'max_active': MAX_ACTIVE, 'retention_hours': config.RETENTION_HOURS,
            })
        if path == '/api/jobs':
            # Polling also detects a worker that exited without writing its final state.
            with LOCK:
                for job_id, process in list(PROCESSES.items()):
                    if process.poll() is not None:
                        try:
                            job = read_job(job_id)
                            if job['status'] in ('analyzing', 'downloading', 'processing'):
                                job.update(status='error', error='Tiến trình bị gián đoạn. Bạn có thể thử lại.')
                                write_json(JOBS / f'{job_id}.json', job)
                        except UserError:
                            pass
                        del PROCESSES[job_id]
            return self.json_response({'jobs': all_jobs()})
        if path.startswith('/api/file/'):
            return self.serve_download(path.removeprefix('/api/file/'))
        assets = {'/': 'index.html', '/index.html': 'index.html', '/styles.css': 'styles.css',
                  '/app.js': 'app.js', '/favicon.JPEG': 'favicon.JPEG'}
        if path not in assets:
            return self.json_response({'error': 'Không tìm thấy trang.'}, 404)
        target = ROOT / assets[path]
        if not target.is_file():
            return self.json_response({'error': 'Không tìm thấy tệp.'}, 404)
        payload = target.read_bytes()
        self.send_response(200)
        self.send_common()
        self.send_header('Content-Type', mimetypes.guess_type(target)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_download(self, job_id):
        try:
            job = read_job(job_id)
            if job['status'] != 'completed' or not job.get('filename'):
                raise UserError('Tệp chưa sẵn sàng để lưu.')
            folder = (DOWNLOADS / job_id).resolve()
            file = (folder / job['filename']).resolve()
            if file.parent != folder or not file.is_file():
                raise UserError('Tệp không còn tồn tại. Vui lòng tải lại video.')
            size = file.stat().st_size
            start, end = 0, size - 1
            status = 200
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                if not match or not any(match.groups()):
                    return self.json_response({'error': 'Range không hợp lệ.'}, 416)
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                status = 206
            self.send_response(status)
            self.send_common()
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', "attachment; filename=video." + file.suffix.lstrip('.') + "; filename*=UTF-8''" + quote(file.name))
            self.send_header('Accept-Ranges', 'bytes')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            with file.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except UserError as error:
            self.json_response({'error': str(error)}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self.safe_host():
            return self.json_response({'error': 'Tên miền truy cập không được phép.'}, 403)
        if not self.authorized():
            return
        if not self.safe_host() or not secrets.compare_digest(self.headers.get('X-DownVideo-Token', ''), TOKEN):
            return self.json_response({'error': 'Phiên hết hạn. Vui lòng tải lại trang.'}, 403)
        origin = self.headers.get('Origin')
        if origin:
            try:
                origin_host = urlsplit(origin).hostname
            except ValueError:
                origin_host = None
            allowed_origin = origin.rstrip('/') == config.PUBLIC_ORIGIN if config.PUBLIC else False
            if not allowed_origin and (config.PUBLIC or origin_host not in ('127.0.0.1', 'localhost', '::1')):
                return self.json_response({'error': 'Nguồn truy cập không được phép.'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length < 1 or length > 32768:
                raise UserError('Dữ liệu gửi lên không hợp lệ.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise UserError('Dữ liệu phải là một đối tượng JSON.')
            path = urlsplit(self.path).path
            with LOCK:
                if path == '/api/analyze':
                    check_capacity()
                    url = validate_url(body.get('url', ''))
                    job_id = secrets.token_hex(16)
                    job = {'id': job_id, 'url': url, 'status': 'analyzing',
                           'created_at': time.time(), 'updated_at': time.time(), 'progress': 0}
                    launch(job, 'analyze')
                    return self.json_response({'job': public_job(job)}, 202)
                job = read_job(str(body.get('id', '')))
                job_id = job['id']
                process = PROCESSES.get(job_id)
                running = process is not None and process.poll() is None
                if running and job['status'] in ('ready', 'completed', 'error', 'cancelled'):
                    try:
                        process.wait(timeout=2)
                        running = False
                    except subprocess.TimeoutExpired:
                        pass
                if path == '/api/download':
                    check_capacity()
                    if running or job['status'].startswith('queued_'):
                        raise UserError('Video này đang được xử lý.')
                    if job['status'] not in ('ready', 'error', 'cancelled', 'completed') or not job.get('formats'):
                        raise UserError('Hãy phân tích link thành công trước khi tải.')
                    quality = str(body.get('quality', 'best'))
                    fps = str(body.get('fps', 'original'))
                    container = str(body.get('container', 'auto'))
                    selection = str(body.get('selection', 'best'))
                    if quality not in ('best', '2160', '1440', '1080', '720', '480') or fps not in ('original', '120', '60', '30') or container not in ('auto', 'mp4', 'mkv', 'mp3'):
                        raise UserError('Tùy chọn tải không hợp lệ.')
                    if selection != 'best' and selection not in [item['key'] for item in job['formats']]:
                        raise UserError('Chất lượng này không có trong video.')
                    job.update(status='downloading', progress=0, error='', filename='',
                               selection=selection, quality=quality, fps=fps, container=container)
                    launch(job, 'download')
                    return self.json_response({'job': public_job(job)}, 202)
                if path == '/api/cancel':
                    if running:
                        # Kill only this job's process tree, including its own FFmpeg child.
                        stop_worker(process)
                    if job['status'] not in ('analyzing', 'downloading', 'processing', 'queued_analyze', 'queued_download'):
                        raise UserError('Video này hiện không chạy.')
                    job = read_job(job_id)
                    job.update(status='cancelled', error='', updated_at=time.time())
                    write_json(JOBS / f'{job_id}.json', job)
                    return self.json_response({'job': public_job(job)})
                if path == '/api/remove':
                    if running or job['status'].startswith('queued_'):
                        raise UserError('Hãy hủy tác vụ trước khi ẩn khỏi lịch sử.')
                    (JOBS / f'{job_id}.json').unlink(missing_ok=True)
                    return self.json_response({'ok': True})
                raise UserError('Không tìm thấy thao tác.')
        except (UserError, ValueError, TypeError) as error:
            self.json_response({'error': str(error) if isinstance(error, UserError) else 'Dữ liệu gửi lên không hợp lệ.'}, 400)
        except Exception:
            self.json_response({'error': 'Không thể xử lý yêu cầu. Hãy thử lại.'}, 500)


def main():
    config.validate_public_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    JOBS.mkdir(parents=True, exist_ok=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for job in all_jobs():
        if job['status'] in ('analyzing', 'downloading', 'processing', 'queued_analyze', 'queued_download'):
            full = read_job(job['id'])
            full.update(status='error', error='Máy chủ đã khởi động lại. Bạn có thể thử lại.')
            write_json(JOBS / f"{job['id']}.json", full)
    address = '0.0.0.0' if config.PUBLIC else '127.0.0.1'
    server = ThreadingHTTPServer((address, args.port), Handler)
    server.daemon_threads = True
    server.timeout = 1
    signal.signal(signal.SIGTERM, lambda signum, frame: STOP.set())
    threading.Thread(target=schedule_jobs, daemon=True).start()
    print(f'DownVideo is ready: {config.PUBLIC_ORIGIN if config.PUBLIC else f"http://127.0.0.1:{args.port}"}', flush=True)
    try:
        while not STOP.is_set():
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        server.server_close()
        with LOCK:
            for process in PROCESSES.values():
                if process.poll() is None:
                    stop_worker(process)


if __name__ == '__main__':
    main()

