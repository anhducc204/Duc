"""Real HTTP checks for the authenticated, single-owner hosted deployment."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


class PublicDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qa_root = ROOT / '.qa'
        qa_root.mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='public-http-', dir=qa_root)
        cls.data_root = Path(cls.temporary.name).resolve()
        cls.process = None
        try:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                cls.port = reservation.getsockname()[1]
            cls.base = f'http://127.0.0.1:{cls.port}'
            cls.origin = 'https://downvideo-deployment-test.example'
            password = secrets.token_urlsafe(32)
            credentials = base64.b64encode(('owner:' + password).encode()).decode()
            cls.authorization = 'Basic ' + credentials
            cls.environment = {key: value for key, value in os.environ.items()
                               if not key.startswith('DOWNVIDEO_') and key not in ('PORT', 'RENDER_EXTERNAL_URL')}
            cls.environment.update({
                'DOWNVIDEO_PUBLIC': '1',
                'DOWNVIDEO_PUBLIC_ORIGIN': cls.origin,
                'DOWNVIDEO_ACCESS_USER': 'owner',
                'DOWNVIDEO_ACCESS_PASSWORD': password,
                'DOWNVIDEO_DATA_ROOT': str(cls.data_root),
                'PORT': str(cls.port),
            })
            cls.process = subprocess.Popen(
                [sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=cls.environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    output, error = cls.process.communicate()
                    raise RuntimeError('Public test server failed to start: ' + error.decode(errors='replace'))
                try:
                    status, _, payload = cls.request('/healthz')
                    if status == 200 and json.loads(payload) == {'status': 'ok'}:
                        break
                except (OSError, ValueError):
                    time.sleep(.1)
            else:
                raise RuntimeError('Public test server did not become healthy within 12 seconds.')
            status, _, payload = cls.request('/api/config', authenticated=True)
            if status != 200:
                raise RuntimeError('Authenticated test configuration request failed.')
            cls.token = json.loads(payload)['token']
        except BaseException:
            cls.cleanup()
            raise

    @classmethod
    def cleanup(cls):
        process = cls.process
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        # TemporaryDirectory owns only this random test directory inside .qa.
        assert cls.data_root.parent == (ROOT / '.qa').resolve()
        cls.temporary.cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    @classmethod
    def request(cls, path, authenticated=False, headers=None, data=None):
        supplied_headers = {'Host': 'downvideo-deployment-test.example'}
        if authenticated:
            supplied_headers['Authorization'] = cls.authorization
        if headers:
            supplied_headers.update(headers)
        payload = None
        if data is not None:
            payload = json.dumps(data).encode()
            supplied_headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(cls.base + path, data=payload, headers=supplied_headers)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_health_check_is_public_and_has_no_secrets(self):
        status, _, payload = self.request('/healthz')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), {'status': 'ok'})

    def test_all_application_routes_require_authentication(self):
        for path in ('/', '/app.js', '/api/config', '/api/jobs', '/api/file/' + 'a' * 32):
            with self.subTest(path=path):
                status, headers, payload = self.request(path)
                self.assertEqual(status, 401)
                self.assertTrue(headers.get('WWW-Authenticate', '').startswith('Basic '))
                self.assertNotIn(b'token', payload)

    def test_correct_authentication_reads_configuration_and_jobs(self):
        status, _, payload = self.request('/api/config', authenticated=True)
        self.assertEqual(status, 200)
        config = json.loads(payload)
        self.assertTrue(config['hosted'])
        self.assertTrue(bool(config.get('token')))
        status, _, payload = self.request('/api/jobs', authenticated=True)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), {'jobs': []})
        self.assertTrue((self.data_root / 'state' / 'jobs').is_dir())
        self.assertTrue((self.data_root / 'downloads').is_dir())

    def test_wrong_host_is_rejected_even_with_authentication(self):
        status, _, _ = self.request('/api/config', authenticated=True, headers={'Host': 'unrelated.example'})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_rejected_before_video_processing(self):
        status, _, _ = self.request('/api/analyze', authenticated=True, headers={
            'Origin': 'https://unrelated.example', 'X-DownVideo-Token': self.token,
        }, data={'url': 'https://example.com/video.mp4'})
        self.assertEqual(status, 403)

    def test_public_mode_does_not_trust_a_localhost_origin(self):
        status, _, _ = self.request('/api/analyze', authenticated=True, headers={
            'Origin': 'http://localhost:9999', 'X-DownVideo-Token': self.token,
        }, data={'url': 'https://example.com/video.mp4'})
        self.assertEqual(status, 403)

    def test_invalid_authentication_is_rejected(self):
        for authorization in ('Basic not-valid-base64!', 'Bearer untrusted', 'Basic ' + base64.b64encode(b'owner:wrong').decode()):
            with self.subTest(kind=authorization.split()[0]):
                status, _, _ = self.request('/api/config', headers={'Authorization': authorization})
                self.assertEqual(status, 401)

    def test_post_requires_authentication_and_csrf_token(self):
        status, _, _ = self.request('/api/remove', data={'id': 'a' * 32})
        self.assertEqual(status, 401)
        status, _, _ = self.request('/api/remove', authenticated=True,
                                    headers={'Origin': self.origin}, data={'id': 'a' * 32})
        self.assertEqual(status, 403)

    def test_valid_origin_reaches_input_validation_without_network(self):
        status, _, payload = self.request('/api/analyze', authenticated=True, headers={
            'Origin': self.origin, 'X-DownVideo-Token': self.token,
        }, data={'url': 'file:///private.mp4'})
        self.assertEqual(status, 400)
        self.assertTrue(bool(json.loads(payload).get('error')))

    def test_startup_rejects_a_weak_public_password(self):
        environment = dict(self.environment, DOWNVIDEO_ACCESS_PASSWORD='short')
        process = subprocess.run([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=environment,
                                 capture_output=True, timeout=10,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b'DOWNVIDEO_ACCESS_PASSWORD', process.stderr)


if __name__ == '__main__':
    unittest.main()

