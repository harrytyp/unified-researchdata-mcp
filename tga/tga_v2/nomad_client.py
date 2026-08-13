"""NOMAD Oasis REST client (PAT auth) — extracted from tga_nomad_app.pyw, unchanged."""
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()


class NomadApiError(Exception):
    """Raised for HTTP-level API failures (4xx/5xx)."""

    def __init__(self, status, detail=''):
        self.status = status
        self.detail = detail
        super().__init__(f'NOMAD API error {status}: {detail or "unknown"}')


class NomadClient:
    """Minimal NOMAD Oasis REST client (PAT auth)."""

    def __init__(self, base_url, pat, verify=False, timeout=20):
        self.base_url = base_url.rstrip('/')
        self.pat = pat or ''
        self.verify = verify
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify

    def _headers(self):
        if not self.pat:
            raise NomadApiError(401, 'No PAT configured')
        return {'Authorization': f'Bearer {self.pat}'}

    def _request(self, method, path, **kwargs):
        url = f'{self.base_url}/api/v1{path}'
        kwargs.setdefault('headers', self._headers())
        kwargs.setdefault('timeout', self.timeout)
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.exceptions.Timeout:
            raise NomadApiError(0, f'Timeout after {self.timeout}s: {path}')
        except requests.exceptions.ConnectionError as e:
            raise NomadApiError(0, f'Connection failed: {e}')
        except requests.exceptions.RequestException as e:
            raise NomadApiError(0, f'Request failed: {e}')
        if resp.status_code >= 400:
            detail = ''
            try:
                detail = resp.json().get('detail', '') or ''
            except Exception:
                detail = resp.text[:200]
            raise NomadApiError(resp.status_code, detail)
        return resp

    def list_uploads(self, per_page=100, published=None):
        """All uploads the PAT can see (admin sees everything).

        The API caps page_size at 10 regardless of per_page and paginates
        via page_after_value — so we loop until all pages are fetched.
        """
        params = {'page_size': min(per_page, 100)}
        if published is not None:
            params['published'] = 'true' if published else 'false'
        all_data = []
        page_after = None
        total = None
        while True:
            p = dict(params)
            if page_after:
                p['page_after_value'] = page_after
            resp = self._request('GET', '/uploads', params=p)
            data = resp.json()
            page = data.get('data', data) if isinstance(data, dict) else data
            all_data.extend(page)
            pag = data.get('pagination', {}) if isinstance(data, dict) else {}
            total = pag.get('total')
            page_after = pag.get('next_page_after_value')
            if not page_after or (total is not None and len(all_data) >= total):
                break
        return all_data

    def get_upload(self, upload_id):
        resp = self._request('GET', f'/uploads/{upload_id}')
        data = resp.json()
        return data.get('data', data) if isinstance(data, dict) else data

    def list_raw_files(self, upload_id):
        """List raw files of an upload as flat [{'name','size','is_file'}]."""
        try:
            resp = self._request('GET', f'/uploads/{upload_id}/rawdir/')
            data = resp.json()
        except NomadApiError as e:
            if e.status == 404:
                return []
            raise
        if isinstance(data, dict):
            meta = data.get('directory_metadata') or {}
            content = meta.get('content') or []
            out = []
            for item in content:
                if isinstance(item, dict):
                    out.append({'name': item.get('name', ''),
                                'path': item.get('name', ''),
                                'size': item.get('size', 0),
                                'is_file': item.get('is_file', True)})
                else:
                    out.append({'name': str(item), 'path': str(item),
                                'size': 0, 'is_file': True})
            return out
        return data if isinstance(data, list) else []

    def download_raw(self, upload_id, rel_path, dest_path):
        """Download a raw file to dest_path; returns bytes count."""
        resp = self._request('GET', f'/uploads/{upload_id}/raw/{rel_path}')
        Path(dest_path).write_bytes(resp.content)
        return len(resp.content)

    def download_raw_bytes(self, upload_id, rel_path):
        """Download a raw file and return its bytes (for in-app preview)."""
        resp = self._request('GET', f'/uploads/{upload_id}/raw/{rel_path}')
        return resp.content

    def upload_raw(self, upload_id, rel_path, filepath):
        """PUT a local file into the upload's raw directory.

        NOMAD 1.4.2: the URL path is the target directory and the filename
        is passed as the ``file_name`` query parameter (streaming method 2).
        """
        name = Path(filepath).name
        target_dir = str(Path(rel_path).parent) if Path(rel_path).parent != Path('.') else ''
        url_path = f'/uploads/{upload_id}/raw/{target_dir}'
        if target_dir:
            url_path = url_path.rstrip('/') + '/'
        with open(filepath, 'rb') as f:
            resp = self._request(
                'PUT', url_path,
                params={'file_name': name},
                data=f, headers={**self._headers(), 'Content-Type': 'application/octet-stream'},
            )
        return resp.status_code in (200, 201, 204)

    def trigger_process(self, upload_id):
        """Trigger (re-)processing of the upload (parses the new .tri)."""
        resp = self._request('POST', f'/uploads/{upload_id}/action/process', json={})
        return resp.status_code in (200, 201, 202)

    def list_upload_entries(self, upload_id):
        resp = self._request('GET', f'/uploads/{upload_id}/entries')
        data = resp.json()
        return data.get('data', data) if isinstance(data, dict) else data

    def check_health(self):
        """Verify PAT + connectivity; returns (ok, message)."""
        try:
            self._request('GET', '/info')
            return True, 'Connected to NOMAD'
        except NomadApiError as e:
            return False, str(e)
