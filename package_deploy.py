"""Create an allowlisted source archive without runtime packages, videos or secrets."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = (
    '.gitignore', '.dockerignore', '.env.example', '.htaccess',
    'Dockerfile', 'render.yaml', 'render.persistent.yaml', 'compose.yaml', 'Caddyfile',
    'server.py', 'deployment.py', 'downloader.py', 'requirements.txt', 'setup.py',
    'index.html', 'styles.css', 'app.js', 'favicon.JPEG', 'api.php',
    'start.bat', 'start.ps1', 'README.md', 'DEPLOY.md',
    'test_backend.py', 'test_deployment.py', 'package_deploy.py',
)


def main():
    output = ROOT / 'deploy-artifact' / 'DownVideo-source.zip'
    output.parent.mkdir(exist_ok=True)
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise ValueError('Missing deployment sources: ' + ', '.join(missing))
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == set(FILES)
        assert archive.testzip() is None
    print(f'Source archive ready: {output} ({output.stat().st_size} bytes, {len(FILES)} files)')


if __name__ == '__main__':
    main()

