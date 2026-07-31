"""elabFTW ↔ NOMAD bidirectional bridge.

Normalizer that runs inside NOMAD to auto-link entries with elabFTW.
Supports both experiments and database items (resources).
API keys: entry config > user Settings entry > shared config.
"""

from typing import Optional
from datetime import datetime, timezone
import requests


class ElabftwBridge:
    """Handles bidirectional communication with elabFTW API."""

    def __init__(self, archive, logger):
        self.archive = archive
        self.logger = logger
        self._api_key = None
        self._api_base = None

    @property
    def api_base(self) -> Optional[str]:
        if self._api_base:
            return self._api_base
        data = self.archive.data
        if hasattr(data, 'config') and data.config:
            if getattr(data.config, 'api_base_url', None):
                self._api_base = data.config.api_base_url
                return self._api_base
        self._api_base = self._from_settings('api_base_url',
                      'https://elntest.ub.tum.de/api/v2')
        return self._api_base

    @property
    def api_key(self) -> Optional[str]:
        if self._api_key:
            return self._api_key
        data = self.archive.data
        if hasattr(data, 'config') and data.config:
            if getattr(data.config, 'api_key', None):
                self._api_key = data.config.api_key
                return self._api_key
        key = self._from_settings('api_key')
        if key:
            self._api_key = key
            return self._api_key
        return None

    def _from_settings(self, key, default=None):
        try:
            from nomad.search import search, MetadataPagination
            user_id = None
            if self.archive.metadata and self.archive.metadata.main_author:
                user_id = self.archive.metadata.main_author.user_id
            result = search(
                owner="user" if user_id else "all",
                query={"entry_name": "elabFTW Settings"},
                pagination=MetadataPagination(page_size=1),
                user_id=user_id,
            )
            if result.pagination.total > 0 and result.data:
                entry = result.data[0]
                upload_id = entry.get("upload_id")
                entry_id = entry.get("entry_id")
                if upload_id and entry_id:
                    url = f"http://localhost:8000/nomad-oasis/api/v1/uploads/{upload_id}/archive/{entry_id}"
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        cfg = data.get("data", {}).get("config", {})
                        return cfg.get(key, default)
        except Exception as e:
            self.logger.debug(f"Settings lookup: {e}")
        return default

    def headers(self):
        return {"Authorization": self.api_key or ""}

    def _entity_type(self):
        data = self.archive.data
        if hasattr(data, 'config') and data.config:
            return getattr(data.config, 'entity_type', 'experiment') or 'experiment'
        return 'experiment'

    def _endpoint(self, entity_type, entity_id=None, suffix=""):
        base = self.api_base or 'https://elntest.ub.tum.de/api/v2'
        if entity_type == 'item':
            ep = f"{base}/items/{entity_id}" if entity_id else f"{base}/items"
        else:
            ep = f"{base}/experiments/{entity_id}" if entity_id else f"{base}/experiments"
        return ep + suffix

    def fetch_entity(self, entity_id: str, entity_type: str = None) -> Optional[dict]:
        etype = entity_type or self._entity_type()
        url = self._endpoint(etype, entity_id, "?format=json&json=true")
        try:
            resp = requests.get(url, headers=self.headers(), timeout=15)
            if resp.status_code == 200:
                return resp.json()
            self.logger.warning(f"Fetch {etype} {entity_id}: HTTP {resp.status_code}")
        except Exception as e:
            self.logger.error(f"Fetch {etype} {entity_id}: {e}")
        return None

    def create_entity(self, title: str, body: str = "", entity_type: str = None) -> Optional[str]:
        etype = entity_type or self._entity_type()
        url = self._endpoint(etype)
        try:
            resp = requests.post(url, headers=self.headers(), json={"title": title, "body": body}, timeout=15)
            if resp.status_code in (200, 201):
                try:
                    return str(resp.json().get("id"))
                except (ValueError, AttributeError):
                    loc = resp.headers.get("Location", "")
                    if loc:
                        return loc.rstrip("/").split("/")[-1]
        except Exception as e:
            self.logger.error(f"Create {etype}: {e}")
        return None

    def add_nomad_link_to_elabftw(self, entity_id: str, nomad_url: str, entity_type: str = None,
                                  entry_name: str = "") -> bool:
        etype = entity_type or self._entity_type()
        import json as _json
        now_str = datetime.now(timezone.utc).isoformat()
        # Write link to metadata (for programmatic access)
        payload = {"metadata": _json.dumps({
            "nomad_url": nomad_url,
            "nomad_synced": now_str
        })}
        # Also write a clickable link in the body (for user interaction)
        body_html = (
            f"<p>This experiment is linked to NOMAD entry <strong>{_json.dumps(entry_name) if entry_name else 'NOMAD'}</strong>.</p>"
            f"<p><a href=\"{nomad_url}\" target=\"_blank\" rel=\"noopener noreferrer\">\U0001f517 Open in NOMAD Oasis</a></p>"
            f"<hr><p><em>Synced via three-way bridge at {now_str}</em></p>"
        )
        payload["body"] = body_html
        try:
            resp = requests.patch(
                self._endpoint(etype, entity_id),
                headers=self.headers(),
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 201, 204):
                return True
            if resp.status_code == 403:
                self.logger.warning(f"Write forbidden on {etype} {entity_id}")
                return False
            return False
        except Exception as e:
            self.logger.error(f"Link-back {etype} {entity_id}: {e}")
        return False


def normalize(archive, logger) -> Optional[bool]:
    try:
        bridge = ElabftwBridge(archive, logger)
        if not bridge.api_base or not bridge.api_key:
            return None
        metadata = archive.metadata
        if not metadata:
            return None
        data = archive.data
        external_id = getattr(metadata, 'external_id', None)
        entry_id = getattr(metadata, 'entry_id', None)
        upload_id = getattr(metadata, 'upload_id', None)
        nomad_url = (
            f"https://researchmcp.duckdns.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}"
            if entry_id else None
        )
        entity_type = 'experiment'
        if hasattr(data, 'config') and data.config:
            entity_type = getattr(data.config, 'entity_type', 'experiment') or 'experiment'
        entry_name = getattr(metadata, 'entry_name', None) or getattr(data, 'title', '') or ''
        if external_id:
            eid = str(external_id)
            logger.info(f"Bridge: linking to {entity_type} {eid}")
            entity = bridge.fetch_entity(eid, entity_type)
            if entity and nomad_url:
                bridge.add_nomad_link_to_elabftw(eid, nomad_url, entity_type, entry_name=entry_name)
        if hasattr(data, 'config') and data.config:
            if getattr(data.config, 'create_elabftw_experiment', False):
                title = getattr(metadata, 'entry_name', None) or getattr(data, 'title', 'NOMAD Entry') or 'NOMAD Entry'
                logger.info(f"Bridge: creating {entity_type} '{title}'")
                eid = bridge.create_entity(title=title, entity_type=entity_type)
                if eid:
                    metadata.external_id = eid
                    if nomad_url:
                        bridge.add_nomad_link_to_elabftw(eid, nomad_url, entity_type, entry_name=title)
                    data.config.create_elabftw_experiment = False
        if hasattr(data, 'config') and data.config:
            if getattr(data.config, 'api_key', None):
                if bridge._from_settings('api_key'):
                    data.config.api_key = None
                    logger.info("Bridge: cleared entry-level key (using saved settings)")
        return True
    except Exception as e:
        logger.warning(f"Bridge error: {e}")
        return None
