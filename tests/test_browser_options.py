"""Remote acceptance boundaries; no browser or network needed."""
import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pilot_browser_qa import PUBLIC_BASE, parse_args, preview_base, public_base, verify_checkout, verify_remote_build


class BrowserOptionsTests(unittest.TestCase):
    def rejected(self, args):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(args)

    def test_local_default_and_remote_commit_pair(self):
        self.assertIsNone(parse_args([]).base_url)
        args = parse_args(['--base-url', PUBLIC_BASE.rstrip('/'), '--commit', 'a' * 40])
        self.assertEqual(args.base_url, PUBLIC_BASE)
        self.rejected(['--base-url', PUBLIC_BASE])
        self.rejected(['--commit', 'a' * 40])
        for sha in ('main', 'abc123', 'A' * 40):
            self.rejected(['--base-url', PUBLIC_BASE, '--commit', sha])

    def test_only_authorized_https_root(self):
        for value in ('http://byby221b.github.io/Dots-Exploration/',
                      'https://example.org/Dots-Exploration/',
                      'https://byby221b.github.io/other/',
                      'https://user:pass@byby221b.github.io/Dots-Exploration/',
                      PUBLIC_BASE + '?token=x', PUBLIC_BASE + '#fragment',
                      PUBLIC_BASE + '../', PUBLIC_BASE + 'articles/',
                      'http://127.0.0.1:8000/', PUBLIC_BASE + '\n'):
            with self.subTest(url=value), self.assertRaises(argparse.ArgumentTypeError):
                public_base(value)

    def test_increment_arguments_are_complete_and_nonnegative(self):
        self.rejected(['--baseline', '/tmp/catalog.json'])
        self.rejected(['--expect-added-articles', '1'])
        args = ['--baseline', '/tmp/catalog.json']
        for key, value in [('articles', '1'), ('images', '0'), ('trending', '1'), ('exploration', '0')]:
            args += ['--expect-added-' + key, value]
        self.assertEqual(parse_args(args).expect_added_articles, 1)
        self.rejected(args[:-1] + ['-1'])

    def test_remote_does_not_start_a_local_server(self):
        with patch('pilot_browser_qa.ThreadingHTTPServer') as server:
            with preview_base(PUBLIC_BASE) as base:
                self.assertEqual(base, PUBLIC_BASE)
            server.assert_not_called()

    def test_checkout_must_match_and_be_clean(self):
        sha = 'a' * 40
        with patch('pilot_browser_qa.subprocess.check_output', side_effect=[sha.encode(), b'']):
            verify_checkout(sha)
        for outputs in ([b'b' * 40], [sha.encode(), b' M site/index.html'],
                        [sha.encode(), b'?? untracked.txt']):
            with patch('pilot_browser_qa.subprocess.check_output', side_effect=outputs), self.assertRaises(AssertionError):
                verify_checkout(sha)

    def test_remote_bytes_status_redirects_and_disposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / 'site'
            site.mkdir()
            contents = {'index.html': b'<p>Reviewed</p>', 'catalog.json': b'{}', 'assets/figure.png': b'image bytes'}
            for name, data in contents.items():
                path = site / name
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(data)
            manifest = json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}).encode()
            (site / 'build-manifest.json').write_bytes(manifest)
            contents['build-manifest.json'] = manifest
            for failure in (None, 'stale', 'missing', 'redirect', 'TLS'):
                responses = []
                request = Mock()
                def get(url, **kwargs):
                    self.assertEqual(kwargs, {'max_redirects': 0, 'timeout': 30000})
                    name = url.removeprefix(PUBLIC_BASE)
                    if failure == 'TLS':
                        raise RuntimeError('certificate verification failed')
                    response = Mock(status=404 if failure == 'missing' else 302 if failure == 'redirect' else 200)
                    response.body.return_value = b'stale' if failure == 'stale' else contents[name]
                    responses.append(response)
                    return response
                request.get.side_effect = get
                if failure:
                    with self.assertRaises((AssertionError, RuntimeError)):
                        verify_remote_build(request, PUBLIC_BASE, root)
                else:
                    self.assertEqual(verify_remote_build(request, PUBLIC_BASE, root), hashlib.sha256(manifest).hexdigest())
                    self.assertEqual(request.get.call_count, len(contents))
                for response in responses:
                    response.dispose.assert_called_once()
