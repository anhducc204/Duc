"""Isolated yt-dlp worker. All options are chosen by the app, never a shell."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.runtime' / 'packages'))
from server import DOWNLOADS, JOBS, read_job, write_json
import deployment as config


def video_formats(info):
    return [item for item in (info.get('formats') or [info])
            if item.get('vcodec') != 'none' and item.get('ext') not in ('mp3', 'm4a', 'aac', 'ogg', 'opus', 'wav', 'flac')
            and not item.get('has_drm')
            and item.get('url') and item.get('protocol') != 'mhtml']


def key_for(item):
    return hashlib.sha256(str(item['format_id']).encode()).hexdigest()[:16]


def summarize_formats(info):
    groups = {}
    for item in video_formats(info):
        height = item.get('height') or 0
        fps = item.get('fps') or 0
        group = (height, round(fps, 2), item.get('ext', ''))
        previous = groups.get(group)
        if not previous or (item.get('tbr') or 0) > (previous.get('tbr') or 0):
            groups[group] = item
    result = []
    for item in sorted(groups.values(), key=lambda item: (item.get('height') or 0, item.get('fps') or 0, item.get('tbr') or 0), reverse=True):
        height, fps = item.get('height') or 0, item.get('fps') or 0
        result.append({'key': key_for(item), 'height': height, 'width': item.get('width'),
                       'fps': round(fps, 2), 'ext': item.get('ext', ''),
                       'size': item.get('filesize') or item.get('filesize_approx'),
                       'has_audio': item.get('acodec') != 'none' if item.get('acodec') else None})
    return result[:80]


def safe_error(error):
    text = re.sub(r'\x1b\[[0-9;]*m', '', str(error))
    text = re.sub(r'https?://\S+', '[link]', text)
    lower = text.lower()
    if any(word in lower for word in ('drm', 'protected')):
        return 'Video được bảo vệ bằng DRM và không thể tải bằng công cụ này.'
    if any(word in lower for word in ('sign in', 'login', 'cookies', 'private video', 'authentication', 'bot')):
        return 'Nguồn yêu cầu đăng nhập hoặc xác minh. Hãy dùng một link video công khai khác.'
    if 'unsupported url' in lower or 'no video' in lower:
        return 'Chưa tìm thấy video tải được tại link này. Hãy thử link trực tiếp đến video.'
    if any(word in lower for word in ('403', 'geo', 'not available', 'unavailable')):
        return 'Nguồn từ chối truy cập hoặc video không khả dụng tại khu vực hiện tại.'
    if any(word in lower for word in ('timed out', 'connection', 'resolve', 'network')):
        return 'Không kết nối được nguồn video. Kiểm tra Internet rồi thử lại.'
    return text.removeprefix('ERROR: ')[:450] or 'Không xử lý được video. Vui lòng thử lại.'


class Worker:
    def __init__(self, job_id):
        self.job = read_job(job_id)
        self.path = JOBS / f'{job_id}.json'
        self.last_write = 0

    def update(self, **changes):
        self.job.update(changes, updated_at=time.time())
        write_json(self.path, self.job)

    def options(self):
        ffmpeg = config.ffmpeg_path()
        if not ffmpeg:
            raise ValueError('Máy chủ chưa có FFmpeg.')
        options = {'quiet': True, 'no_warnings': True, 'noplaylist': True,
                   'socket_timeout': 25, 'retries': 2, 'fragment_retries': 2,
                   'windowsfilenames': True, 'ffmpeg_location': str(ffmpeg),
                   'cachedir': str(config.STATE / 'yt-cache'),
                   'extractor_retries': 2, 'logger': QuietLogger()}
        deno = config.deno_path()
        if deno:
            options['js_runtimes'] = {'deno': {'path': deno}}
        if config.MAX_FILE_BYTES:
            options['max_filesize'] = config.MAX_FILE_BYTES
        return options

    def analyze(self):
        import yt_dlp
        with yt_dlp.YoutubeDL(self.options()) as ydl:
            info = ydl.extract_info(self.job['url'], download=False)
        if not info or info.get('_type') in ('playlist', 'multi_video'):
            raise ValueError('Hãy dán link một video cụ thể thay vì toàn bộ danh sách phát.')
        if info.get('is_live'):
            raise ValueError('Video đang phát trực tiếp. Hãy thử lại sau khi buổi phát kết thúc.')
        formats = summarize_formats(info)
        if not formats:
            raise ValueError('Nguồn không cung cấp định dạng video công khai để tải.')
        thumbnail = info.get('thumbnail') or ''
        if urlsplit(thumbnail).scheme not in ('http', 'https'):
            thumbnail = ''
        self.update(status='ready', title=info.get('title') or 'Video',
                    uploader=info.get('uploader') or info.get('channel') or '',
                    source=info.get('extractor_key') or urlsplit(self.job['url']).hostname,
                    thumbnail=thumbnail, duration=info.get('duration'), formats=formats,
                    has_audio=(any(item.get('acodec') != 'none' for item in info.get('formats', []))
                               if any(item.get('acodec') for item in info.get('formats', [])) else None),
                    error='', progress=0)

    def choose(self, context):
        formats = [item for item in context['formats'] if not item.get('has_drm')]
        videos = video_formats({'formats': formats})
        if self.job['selection'] != 'best':
            videos = [item for item in videos if key_for(item) == self.job['selection']]
        else:
            if self.job['quality'] != 'best':
                videos = [item for item in videos if item.get('height') and item['height'] <= int(self.job['quality'])]
            if self.job['fps'] != 'original':
                videos = [item for item in videos if not item.get('fps') or item['fps'] <= int(self.job['fps']) + .1]
        if not videos:
            raise ValueError('Không có định dạng khớp lựa chọn. Hãy chọn Chất lượng gốc hoặc phân tích lại link.')
        video = max(videos, key=lambda item: (item.get('height') or 0, item.get('fps') or 0, item.get('tbr') or 0))
        self.update(actual_height=video.get('height'), actual_fps=video.get('fps'))
        if video.get('acodec') != 'none':
            yield video
            return
        audios = [item for item in formats if item.get('vcodec') == 'none' and item.get('acodec') not in (None, 'none')]
        if not audios:
            yield video
            return
        audio = audios[-1]
        yield {'format_id': f"{video['format_id']}+{audio['format_id']}",
               'ext': 'mkv' if self.job['container'] == 'auto' else self.job['container'],
               'requested_formats': [video, audio],
               'protocol': f"{video['protocol']}+{audio['protocol']}"}

    def progress(self, data):
        now = time.monotonic()
        if now - self.last_write < .5 and data['status'] != 'finished':
            return
        self.last_write = now
        total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
        downloaded = data.get('downloaded_bytes') or 0
        if config.MAX_FILE_BYTES and downloaded > config.MAX_FILE_BYTES:
            raise ValueError('Video vượt dung lượng cho phép của máy chủ. Hãy chọn chất lượng thấp hơn.')
        if config.MAX_STORAGE_BYTES and config.storage_usage() >= config.MAX_STORAGE_BYTES:
            raise ValueError('Máy chủ đã đạt giới hạn lưu trữ. Vui lòng thử lại sau.')
        progress = min(99, downloaded / total * 100) if total else 0
        self.update(status='downloading' if data['status'] != 'finished' else 'processing',
                    progress=round(progress, 1), downloaded_bytes=downloaded, total_bytes=total,
                    speed=data.get('speed') or 0, eta=data.get('eta'))

    def postprocess(self, data):
        self.update(status='processing', progress=99, speed=0, eta=None)

    def download(self):
        import yt_dlp
        folder = DOWNLOADS / self.job['id']
        folder.mkdir(parents=True, exist_ok=True)
        options = self.options()
        options.update({'format': self.choose, 'outtmpl': str(folder / '%(title).150B [%(id)s].%(ext)s'),
                        'progress_hooks': [self.progress], 'postprocessor_hooks': [self.postprocess],
                        'overwrites': True, 'continuedl': True, 'concurrent_fragment_downloads': 4})
        container = self.job['container']
        if container == 'mp3':
            options['format'] = 'bestaudio/best'
            options['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
        elif container in ('mp4', 'mkv'):
            options['merge_output_format'] = container
            options['postprocessors'] = [{'key': 'FFmpegVideoRemuxer', 'preferedformat': container}]
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(self.job['url'], download=True)
            if not info:
                raise ValueError('Nguồn không trả về video tải được.')
        allowed = {'.mp4', '.mkv', '.webm', '.mov', '.mp3', '.m4a', '.aac', '.flv', '.avi', '.ts', '.ogg', '.opus'}
        files = [file for file in folder.iterdir() if file.is_file() and file.suffix.lower() in allowed
                 and not re.search(r'\.f\d+\.', file.name)]
        if not files:
            raise ValueError('Không tạo được tệp hoàn chỉnh. Hãy chọn định dạng Gốc rồi thử lại.')
        file = max(files, key=lambda item: item.stat().st_mtime_ns)
        # Generic direct links often omit dimensions. Read the completed local file.
        metadata = subprocess.run([config.ffmpeg_path(), '-hide_banner', '-i', str(file)],
                                  capture_output=True, timeout=20,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stderr.decode('utf-8', errors='replace')
        video = re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b.*?(\d+(?:\.\d+)?) fps', metadata)
        if video:
            self.job.update(actual_height=int(video[2]), actual_fps=float(video[3]))
        self.update(status='completed', progress=100, speed=0, eta=0,
                    filename=file.name, size=file.stat().st_size, error='')


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


if __name__ == '__main__':
    worker = Worker(sys.argv[2])
    try:
        getattr(worker, sys.argv[1])()
    except Exception as error:
        worker.update(status='error', error=safe_error(error), speed=0, eta=None)

