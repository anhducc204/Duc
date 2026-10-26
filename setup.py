"""Install dependencies inside this project, including the YouTube JS runtime."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
PACKAGES = ROOT / '.runtime' / 'packages'


def main():
    if not (PACKAGES / 'yt_dlp').is_dir() or not (PACKAGES / 'imageio_ffmpeg').is_dir():
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--target', str(PACKAGES),
                               '-r', str(ROOT / 'requirements.txt')])
    binary_dir = ROOT / '.runtime' / 'bin'
    binary_dir.mkdir(parents=True, exist_ok=True)
    deno = binary_dir / 'deno.exe'
    if os.name == 'nt' and not deno.is_file():
        print('Downloading the Deno runtime for YouTube support...', flush=True)
        release_request = urllib.request.Request('https://api.github.com/repos/denoland/deno/releases/latest',
                                                headers={'User-Agent': 'DownVideo-Setup/1.0'})
        release = json.loads(urllib.request.urlopen(release_request, timeout=30).read())
        asset = next(item for item in release['assets'] if item['name'] == 'deno-x86_64-pc-windows-msvc.zip')
        base = asset['browser_download_url']
        request = urllib.request.Request(base, headers={'User-Agent': 'DownVideo-Setup/1.0'})
        payload = urllib.request.urlopen(request, timeout=90).read()
        checksum = (asset.get('digest') or '').removeprefix('sha256:')
        if not checksum:
            checksum = urllib.request.urlopen(base + '.sha256sum', timeout=30).read().decode().split()[0]
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise RuntimeError('Deno checksum verification failed.')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            deno.write_bytes(archive.read('deno.exe'))
    print('DownVideo dependencies are ready.', flush=True)


if __name__ == '__main__':
    main()

