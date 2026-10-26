"""Behavior checks for original quality, URL boundaries and request validation."""
import socket
import unittest
from unittest.mock import patch

import server
from downloader import Worker, summarize_formats


def source(height, fps, identifier, drm=False):
    return {'format_id': identifier, 'height': height, 'fps': fps, 'ext': 'mp4',
            'vcodec': 'h264', 'acodec': 'aac', 'has_drm': drm,
            'url': 'https://example.com/video.mp4', 'protocol': 'https', 'tbr': 1000}


class OriginalQualityTests(unittest.TestCase):
    def choose(self, formats, **options):
        worker = Worker.__new__(Worker)
        worker.job = {'selection': 'best', 'quality': 'best', 'fps': 'original', 'container': 'auto', **options}
        worker.update = lambda **changes: None
        return list(worker.choose({'formats': formats}))[0]

    def test_preserves_real_4k_120(self):
        formats = [source(1080, 60, 'a'), source(2160, 60, 'b'), source(2160, 120, 'c')]
        self.assertEqual(self.choose(formats)['format_id'], 'c')

    def test_does_not_invent_4k_or_frames(self):
        selected = self.choose([source(720, 30, 'a')], quality='2160', fps='120')
        self.assertEqual((selected['height'], selected['fps']), (720, 30))

    def test_honors_frame_rate_cap(self):
        formats = [source(2160, 120, 'a'), source(2160, 60, 'b'), source(1080, 30, 'c')]
        self.assertEqual(self.choose(formats, fps='60')['format_id'], 'b')

    def test_reports_unavailable_filter(self):
        with self.assertRaises(ValueError):
            self.choose([source(2160, 120, 'a')], quality='720')

    def test_drm_is_not_offered(self):
        formats = summarize_formats({'formats': [source(2160, 120, 'a', True), source(1080, 60, 'b')]})
        self.assertEqual(len(formats), 1)
        self.assertEqual(formats[0]['height'], 1080)

    def test_direct_mp4_without_codec_metadata_is_downloadable(self):
        direct = {'format_id': 'mp4', 'ext': 'mp4', 'url': 'https://example.com/a.mp4', 'protocol': 'https'}
        self.assertEqual(len(summarize_formats({'formats': [direct]})), 1)
        self.assertEqual(self.choose([direct])['format_id'], 'mp4')


class URLBoundaryTests(unittest.TestCase):
    def test_rejects_non_http_and_credentials(self):
        for value in ['file:///etc/passwd', 'ftp://example.com/video', 'https://name:pass@example.com/video', 'https://example.com:9000/video', '']:
            with self.subTest(value=value), self.assertRaises(server.UserError):
                server.validate_url(value)

    def test_rejects_private_and_mixed_dns(self):
        for address in ['127.0.0.1', '10.1.2.3', '192.168.1.1', '169.254.169.254', '::1', 'fc00::1']:
            answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
            with self.subTest(address=address), patch('socket.getaddrinfo', return_value=answer), self.assertRaises(server.UserError):
                server.validate_url('https://example.com/video')

    def test_allows_public_url_with_query(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        url = 'https://example.com/watch?v=abc&quality=best'
        with patch('socket.getaddrinfo', return_value=answer):
            self.assertEqual(server.validate_url(url), url)


if __name__ == '__main__':
    unittest.main()

