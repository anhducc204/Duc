"""Runtime configuration for local XAMPP and authenticated Internet deployments."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def integer(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ValueError(f'{name} must be an integer.') from None
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}.')
    return value


PUBLIC = os.environ.get('DOWNVIDEO_PUBLIC') == '1'
PUBLIC_ORIGIN = (os.environ.get('DOWNVIDEO_PUBLIC_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
ACCESS_USER = os.environ.get('DOWNVIDEO_ACCESS_USER', 'owner')
ACCESS_PASSWORD = os.environ.get('DOWNVIDEO_ACCESS_PASSWORD', '')
DATA_ROOT = Path(os.environ['DOWNVIDEO_DATA_ROOT']).resolve() if os.environ.get('DOWNVIDEO_DATA_ROOT') else None
STATE = DATA_ROOT / 'state' if DATA_ROOT else ROOT / '.data'
DOWNLOADS = DATA_ROOT / 'downloads' if DATA_ROOT else ROOT / 'downloads'
MAX_ACTIVE = integer('DOWNVIDEO_MAX_ACTIVE', 2 if PUBLIC else 3, 1, 8)
MAX_QUEUE = integer('DOWNVIDEO_MAX_QUEUE', 50 if PUBLIC else 500, 1, 1000)
MAX_FILE_BYTES = integer('DOWNVIDEO_MAX_FILE_MB', 2048 if PUBLIC else 0, 0, 102400) * 1024 * 1024
MAX_STORAGE_BYTES = integer('DOWNVIDEO_MAX_STORAGE_MB', 10240 if PUBLIC else 0, 0, 1024000) * 1024 * 1024
RETENTION_HOURS = integer('DOWNVIDEO_RETENTION_HOURS', 24 if PUBLIC else 0, 0, 8760)
MAX_JOB_SECONDS = integer('DOWNVIDEO_MAX_JOB_SECONDS', 7200, 30, 86400)


def public_hostname():
    return urlsplit(PUBLIC_ORIGIN).hostname


def validate_public_settings():
    if not PUBLIC:
        return
    origin = urlsplit(PUBLIC_ORIGIN)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
        raise ValueError('Set DOWNVIDEO_PUBLIC_ORIGIN to the exact HTTPS origin, or deploy with RENDER_EXTERNAL_URL.')
    if len(ACCESS_PASSWORD) < 20 or ACCESS_PASSWORD in ('change-this-password-before-deploying', 'replace-with-a-random-password'):
        raise ValueError('DOWNVIDEO_ACCESS_PASSWORD must contain at least 20 characters. Use a generated secret.')
    if not ACCESS_USER or ':' in ACCESS_USER:
        raise ValueError('DOWNVIDEO_ACCESS_USER must be nonempty and contain no colon.')
    if not all((MAX_FILE_BYTES, MAX_STORAGE_BYTES, RETENTION_HOURS)):
        raise ValueError('Public deployment requires nonzero file, storage and retention limits.')


def deno_path():
    bundled = ROOT / '.runtime' / 'bin' / ('deno.exe' if os.name == 'nt' else 'deno')
    return str(bundled) if bundled.is_file() else shutil.which('deno')


def ffmpeg_path():
    executable = shutil.which('ffmpeg')
    if executable:
        return executable
    binaries = ROOT / '.runtime' / 'packages' / 'imageio_ffmpeg' / 'binaries'
    for bundled in binaries.glob('ffmpeg-*'):
        if bundled.is_file() and (bundled.suffix.lower() == '.exe' or os.access(bundled, os.X_OK)):
            return str(bundled)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def engine_ready():
    return importlib.util.find_spec('yt_dlp') is not None or (ROOT / '.runtime' / 'packages' / 'yt_dlp').is_dir()


def storage_usage():
    total = 0
    if DOWNLOADS.is_dir():
        for path in DOWNLOADS.rglob('*'):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
    return total

