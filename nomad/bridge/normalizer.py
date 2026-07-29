"""elabFTW ↔ NOMAD bidirectional bridge.

Normalizer that runs inside NOMAD to auto-link entries with elabFTW experiments.
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
        # Fallback to shared config file
        self._api_base = self._from_config('elabftw', 'api_url', 'https://elntest.ub.tum.de/api/v2')
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
        self._api_key = self._from_config('elabftw', 'api_key', '')
        return self._api_key

    def _from_config(self, section, key, default=None):
        """Read value from shared YAML config."""
        import os
        path = '/app/plugins/three_way_sync/config.yaml'
        if os.path.exists(path):
            import yaml
            with open(path) as f:
                cfg = yaml.safe_load(f)
            return cfg.get(section, {}).get(key, default)
        return default

    def headers(self):
        return {"Authorization": self.api_key or ""}

    def fetch_experiment(self, experiment_id: str) -> Optional[dict]:
        url = f"{self.api_base}/experiments/{experiment_id}?format=json&json=true"
        try:
            resp = requests.get(url, headers=self.headers(), timeout=15)
            if resp.status_code == 200:
                return resp.json()
            self.logger.warning(f"elabFTW fetch {experiment_id}: HTTP {resp.status_code}")
        except Exception as e:
            self.logger.error(f"elabFTW fetch {experiment_id}: {e}")
        return None

    def create_experiment(self, title: str, body: str = "") -> Optional[str]:
        url = f"{self.api_base}/experiments"
        try:
            resp = requests.post(url, headers=self.headers(), json={"title": title, "body": body}, timeout=15)
            if resp.status_code in (200, 201):
                return str(resp.json().get('id'))
        except Exception as e:
            self.logger.error(f"elabFTW create: {e}")
        return None

    def add_nomad_link_to_elabftw(self, experiment_id: str, nomad_url: str) -> bool:
        extra = {"NOMAD URL": nomad_url, "NOMAD Synced": datetime.now(timezone.utc).isoformat()}
        try:
            resp = requests.put(
                f"{self.api_base}/experiments/{experiment_id}",
                headers=self.headers(),
                json={"extra_fields": extra},
                timeout=15,
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            self.logger.error(f"elabFTW link-back: {e}")
        return False


def normalize(archive, logger) -> Optional[bool]:
    """
    NOMAD normalizer hook — auto-links entries with elabFTW experiments.

    Called on every entry save. Handles three cases:
    1. Entry has external_id → link to existing elabFTW experiment
    2. Entry has create flag → create new elabFTW experiment
    3. Entry has config.sync_now → sync experiment data
    """
    try:
        bridge = ElabftwBridge(archive, logger)
        if not bridge.api_base or not bridge.api_key:
            return None  # No elabFTW configured — skip

        metadata = archive.metadata
        if not metadata:
            return None

        external_id = getattr(metadata, 'external_id', None)
        entry_id = getattr(metadata, 'entry_id', None)
        upload_id = getattr(metadata, 'upload_id', None)
        entry_name = getattr(metadata, 'entry_name', None)

        nomad_url = (
            f"https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/entry/{upload_id}/{entry_id}"
            if upload_id and entry_id else None
        )

        # Case: external_id set → link to existing elabFTW experiment
        if external_id:
            exp_id = str(external_id)
            logger.info(f"Bridge: linking to elabFTW experiment {exp_id}")
            exp = bridge.fetch_experiment(exp_id)
            if exp and nomad_url:
                bridge.add_nomad_link_to_elabftw(exp_id, nomad_url)
                logger.info(f"Bridge: wrote NOMAD link back to experiment {exp_id}")

        # Case: entry has auto-create flag
        data = archive.data
        if hasattr(data, 'config') and data.config:
            if getattr(data.config, 'create_elabftw_experiment', False):
                title = entry_name or getattr(data, 'title', 'NOMAD Entry') or 'NOMAD Entry'
                logger.info(f"Bridge: creating elabFTW experiment for '{title}'")
                exp_id = bridge.create_experiment(title=title)
                if exp_id:
                    metadata.external_id = exp_id
                    if nomad_url:
                        bridge.add_nomad_link_to_elabftw(exp_id, nomad_url)
                    data.config.create_elabftw_experiment = False

        return True

    except Exception as e:
        logger.warning(f"Bridge error: {e}")
        return None
