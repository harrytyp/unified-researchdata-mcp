"""Tests for the self-updater: version math, digest check, feed handling.

Run:  python -m pytest test_updater.py -q      (in tga/tga_v2)
The network and swap paths are exercised against local fixtures, never a
real release.
"""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import updater


# ── version math ──────────────────────────────────────────────

@pytest.mark.parametrize('remote,current,expected', [
    ('1.3.0', '1.2.0', True),
    ('1.2.1', '1.2.0', True),
    ('1.2', '1.2.0', False),          # missing part counts as 0
    ('1.2.0', '1.2.0', False),
    ('1.1.9', '1.2.0', False),
    ('2.0', '1.99.99', True),
])
def test_is_newer(remote, current, expected):
    assert updater.is_newer(remote, current) is expected


def test_parse_version_tolerates_noise():
    assert updater.parse_version('v1.2.0-beta') == (1, 2, 0)
    assert updater.parse_version('') == (0,)
    assert updater.parse_version(None) == (0,)


# ── digest verification ───────────────────────────────────────

def test_verify_sha256(tmp_path):
    f = tmp_path / 'x.exe'
    payload = b'not really an exe'
    f.write_bytes(payload)
    good = hashlib.sha256(payload).hexdigest()
    assert updater.verify_sha256(f, good)
    assert updater.verify_sha256(f, good.upper())        # case-insensitive
    assert not updater.verify_sha256(f, 'deadbeef')
    assert not updater.verify_sha256(f, '')


# ── feed handling ────────────────────────────────────────────

def test_normalize_and_usable():
    feed = updater.normalize_feed({'version': '1.3.0', 'sha256': 'AB' * 32,
                                   'url': 'https://example.org/TGA_Operator.exe',
                                   'size': 100, 'notes': 'fixes'})
    assert feed['sha256'] == 'ab' * 32
    assert updater.usable(feed)
    assert not updater.usable(updater.normalize_feed({'version': '2.0'}))


class _Handler(BaseHTTPRequestHandler):
    payload = b''
    feed = b'{}'

    def do_GET(self):  # noqa: N802
        body = self.feed if self.path.endswith('.json') else self.payload
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server(tmp_path):
    payload = b'BINARY-PAYLOAD' * 1000
    _Handler.payload = payload
    srv = HTTPServer(('127.0.0.1', 0), _Handler)
    port = srv.server_address[1]
    _Handler.feed = json.dumps({'version': '9.9.9',
                                'url': f'http://127.0.0.1:{port}/TGA_Operator.exe',
                                'sha256': hashlib.sha256(payload).hexdigest(),
                                'size': len(payload)}).encode()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port, payload
    srv.shutdown()


def test_check_reports_newer_only(server):
    port, payload = server
    feed_url = f'http://127.0.0.1:{port}/latest.json'
    assert updater.check(feed_url, current='1.2.0')['version'] == '9.9.9'
    assert updater.check(feed_url, current='10.0') is None


def test_check_survives_dead_host():
    assert updater.check('http://127.0.0.1:1/latest.json', timeout=2) is None


def test_download_verifies_and_refuses_tampered(server, tmp_path):
    port, payload = server
    feed = updater.check(f'http://127.0.0.1:{port}/latest.json', current='1.0')
    assert feed
    local = updater.download(feed, dest_dir=tmp_path)
    assert local.read_bytes() == payload

    bad = dict(feed, sha256='0' * 64, url=f'http://127.0.0.1:{port}/TGA_Operator.exe')
    with pytest.raises(ValueError):
        updater.download(bad, dest_dir=tmp_path)
    assert not list(tmp_path.glob('*.part'))


# ── swap script ──────────────────────────────────────────────

def test_swap_script_waits_and_restarts(tmp_path):
    target = tmp_path / 'TGA_Operator.exe'
    new = tmp_path / 'new.exe'
    target.write_bytes(b'old')
    new.write_bytes(b'new')
    script = updater._swap_script(target, new, 4242)
    raw = script.read_bytes()
    text = raw.decode('utf-8')
    # the retry loop must not depend on `find`, which is GNU find under git-bash
    assert 'find "' not in text and 'tasklist' not in text
    assert ':retry' in text and 'GEQ 60' in text
    assert f'move /Y "{target}" "{target}.old"' in text
    assert f'move /Y "{new}" "{target}"' in text
    assert f'start "" "{target}"' in text
    assert b'\r\n' in raw and raw.count(b'\r\n') == raw.count(b'\n')  # CRLF only, no doubling


def test_install_refuses_without_packaged_exe(tmp_path):
    new = tmp_path / 'new.exe'
    new.write_bytes(b'new')
    with pytest.raises(RuntimeError):
        updater.install(new, tmp_path / 'missing.exe')
