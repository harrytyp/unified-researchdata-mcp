"""Self-update for the operator EXE: feed, verification, swap.

The app is a PyInstaller onefile EXE that the operator double-clicks; there is
no installer and nobody updates it by hand. So:

  * `latest.json` is served from the deployment (web/tga-operator/ in the
    monorepo, reachable at https://researchdata.e-conversion.de/tga-operator/),
  * the binary itself is a GitHub release asset, addressed by the feed,
  * the feed carries the sha256, and nothing is written into place before that
    digest matches the downloaded bytes.

Nothing here runs in a measurement: the swap only happens after the operator
confirms, and it waits for this process to exit before it touches the file.

Pure functions (parse_version / is_newer / verify_sha256 / pick) are separated
from the side-effecting ones so they can be tested without a network or a
running EXE.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from version import APP_VERSION

DEFAULT_FEED = 'https://researchdata.e-conversion.de/tga-operator/latest.json'
CHUNK = 256 * 1024
NL = '\r\n'          # the cmd script must carry CRLF on every Windows line


# ── pure helpers ───────────────────────────────────────────────

def parse_version(value) -> tuple:
    """'1.2.0' -> (1, 2, 0). Non-numeric suffixes are ignored, never raised."""
    parts = re.findall(r'\d+', str(value or ''))
    return tuple(int(p) for p in parts[:4]) or (0,)


def is_newer(remote, current) -> bool:
    """True only for a strictly newer release (missing parts count as 0)."""
    r, c = parse_version(remote), parse_version(current)
    width = max(len(r), len(c))
    return r + (0,) * (width - len(r)) > c + (0,) * (width - len(c))


def verify_sha256(path, expected: str) -> bool:
    """Constant digest comparison; an empty expectation never verifies."""
    expected = (expected or '').strip().lower()
    if not expected:
        return False
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest() == expected


def normalize_feed(feed) -> dict:
    """Accept the documented feed shape and fill what the UI reads."""
    feed = feed if isinstance(feed, dict) else {}
    version = str(feed.get('version') or '').strip()
    url = str(feed.get('url') or '').strip()
    return {
        'version': version,
        'url': url,
        'sha256': str(feed.get('sha256') or '').strip().lower(),
        'size': int(feed.get('size') or 0),
        'notes': str(feed.get('notes') or '').strip(),
        'mandatory': bool(feed.get('mandatory')),
        'page': str(feed.get('page') or '').strip(),
    }


def _is_https(url: str) -> bool:
    """https only - except on the loopback, where the tests serve fixtures."""
    if url.startswith('https://'):
        return True
    return url.startswith(('http://127.0.0.1', 'http://localhost'))


def usable(feed: dict) -> bool:
    """A release we may download: version, an https URL and a sha256."""
    return bool(feed.get('version') and feed.get('sha256')
                and _is_https(feed.get('url', '')))


# ── network ───────────────────────────────────────────────────

def fetch_feed(url=None, timeout=10) -> dict:
    """Read the release feed. Raises nothing the caller has to handle."""
    url = (url or DEFAULT_FEED).strip()
    if not url:
        return {}
    req = urllib.request.Request(url, headers={'User-Agent': f'TGA-Operator/{APP_VERSION}',
                                               'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return normalize_feed(json.loads(resp.read().decode('utf-8')))


def check(feed_url=None, current=None, timeout=10):
    """Return the feed dict when a newer usable release exists, else None."""
    current = current or APP_VERSION
    try:
        feed = fetch_feed(feed_url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    if not usable(feed) or not is_newer(feed['version'], current):
        return None
    return feed


def download(feed: dict, timeout=300, dest_dir=None) -> Path:
    """Download the release, verify its sha256 and return the local path.

    A digest mismatch deletes the partial file and raises, so a corrupted or
    tampered download can never be swapped in.
    """
    dest_dir = Path(dest_dir or (Path.home() / '.tga_updates'))
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"TGA_Operator-{feed['version']}.exe"
    part = target.with_suffix('.part')
    req = urllib.request.Request(feed['url'], headers={
        'User-Agent': f'TGA-Operator/{APP_VERSION}'})
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(part, 'wb') as out:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            digest.update(block)
            out.write(block)
            received += len(block)
    if feed.get('size') and received != feed['size']:
        part.unlink(missing_ok=True)
        raise ValueError(f'size mismatch: got {received}, expected {feed["size"]}')
    if digest.hexdigest() != feed['sha256']:
        part.unlink(missing_ok=True)
        raise ValueError('sha256 mismatch')
    part.replace(target)
    return target


# ── swap ──────────────────────────────────────────────────────

def frozen_exe() -> Path | None:
    """Path of the running EXE, or None when this is a source checkout."""
    if not getattr(sys, 'frozen', False):
        return None
    return Path(sys.executable).resolve()


def _swap_script(target: Path, new_exe: Path, pid: int) -> Path:
    """A cmd script that waits for the app to exit, then replaces the EXE.

    Windows cannot overwrite a running image, but it can rename it - so the
    old file is renamed aside and the new one moved in. The wait is a retry
    loop on that rename rather than `tasklist | find`: `find` resolves to the
    MSYS/GNU find on any machine with git-bash on PATH, and the loop then
    never terminates. Each attempt is one second apart, 60 attempts total.
    """
    script = Path(tempfile.gettempdir()) / f'tga_update_{pid}.cmd'
    lines = [
        '@echo off',
        'chcp 65001 >nul 2>&1',
        'setlocal enabledelayedexpansion',
        'set TRIES=0',
        ':retry',
        f'move /Y "{target}" "{target}.old" >nul 2>&1',
        'if errorlevel 1 (',
        '  set /a TRIES+=1',
        '  if !TRIES! GEQ 60 exit /b 1',
        '  ping -n 2 127.0.0.1 >nul',
        '  goto retry',
        ')',
        f'move /Y "{new_exe}" "{target}" >nul 2>&1',
        'if errorlevel 1 (',
        f'  move /Y "{target}.old" "{target}" >nul 2>&1',
        '  exit /b 1',
        ')',
        f'start "" "{target}"',
        f'del /F /Q "{target}.old" >nul 2>&1',
        'del /F /Q "%~f0" >nul 2>&1',
    ]
    # newline='' keeps the CRLF we write; text mode would double the \r
    script.write_text(NL.join(lines) + NL, encoding='utf-8', newline='')
    return script


def install(new_exe: Path, target: Path | None = None) -> Path:
    """Stage the swap and start it detached. Returns the script path."""
    target = Path(target or frozen_exe() or '')
    if not target or not target.exists():
        raise RuntimeError('not a packaged EXE - nothing to replace')
    script = _swap_script(target, Path(new_exe), os.getpid())
    creationflags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen(['cmd', '/c', str(script)], creationflags=creationflags,
                     close_fds=True, cwd=str(script.parent))
    return script
