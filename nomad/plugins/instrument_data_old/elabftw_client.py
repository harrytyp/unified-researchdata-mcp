"""elabFTW API client for instrument data pipeline.

Handles:
- Searching for experiments by sample name
- Patching experiment body with results
- Uploading processed data files
- Setting experiment status
- Linking back NOMAD URL
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests


class ElabftwClient:
    """Lightweight elabFTW API client for automation."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        team: int = 29,
        timeout: int = 30,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.team = team
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })

    # ── Experiments ──────────────────────────────────────────────────────────

    def find_experiment_by_name(
        self, sample_name: str, category_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Find an experiment by sample name in the configured team."""
        params = {
            "team": self.team,
            "q": sample_name,
            "limit": 10,
        }
        if category_id:
            params["category"] = category_id

        try:
            resp = self.session.get(
                f"{self.api_url}/experiments",
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    # Exact match first, then fuzzy
                    for exp in results:
                        title = exp.get("title", "")
                        if title.lower() == sample_name.lower():
                            return exp
                    return results[0]
        except requests.RequestException:
            pass
        return None

    def find_experiments_by_status(
        self, status_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Find experiments with a specific status."""
        try:
            resp = self.session.get(
                f"{self.api_url}/experiments",
                params={
                    "team": self.team,
                    "status": status_id,
                    "limit": limit,
                },
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return []

    def get_experiment(self, experiment_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single experiment by ID."""
        try:
            resp = self.session.get(
                f"{self.api_url}/experiments/{experiment_id}",
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def update_experiment(
        self,
        experiment_id: int,
        body: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Update an experiment's body, metadata, status, and/or tags."""
        payload: Dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if metadata is not None:
            payload["metadata"] = json.dumps(metadata)
        if status_id is not None:
            payload["status"] = status_id
        if tags is not None:
            payload["tags"] = tags

        if not payload:
            return False

        try:
            resp = self.session.patch(
                f"{self.api_url}/experiments/{experiment_id}",
                json=payload,
                timeout=self.timeout,
            )
            return resp.status_code in (200, 201, 204)
        except requests.RequestException:
            return False

    def upload_file(
        self, experiment_id: int, filepath: str
    ) -> bool:
        """Upload a file as an attachment to an experiment."""
        try:
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                resp = requests.post(
                    f"{self.api_url}/experiments/{experiment_id}/uploads",
                    headers={"Authorization": self.api_key},
                    files=files,
                    timeout=self.timeout * 2,
                )
            return resp.status_code in (200, 201, 204)
        except (requests.RequestException, IOError):
            return False

    def link_experiment_to_item(self, experiment_id: int, item_id: int) -> bool:
        """Link an experiment to a database item (instrument)."""
        try:
            resp = self.session.post(
                f"{self.api_url}/experiments/{experiment_id}/experiments_links",
                json={"link_id": item_id, "link_type": "item"},
                timeout=self.timeout,
            )
            return resp.status_code in (200, 201, 204)
        except requests.RequestException:
            return False

    # ── Status helpers ───────────────────────────────────────────────────────

    def get_team_statuses(self) -> Dict[str, int]:
        """Get mapping of status name -> status ID for the configured team.

        Returns e.g. {"Running": 70, "Success": 123, "Fail": 125}
        """
        try:
            resp = self.session.get(
                f"{self.api_url}/teams/{self.team}/experiments_status",
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return {s["title"]: s["id"] for s in resp.json()}
        except requests.RequestException:
            pass
        return {}

    # ─── Result push-back ────────────────────────────────────────────────────

    def push_tga_results(
        self,
        experiment_id: int,
        sample_name: str,
        signals: Dict[str, List[float]],
        computed: Dict[str, Any],
        nomad_url: str,
        plot_svg: Optional[str] = None,
    ) -> bool:
        """Push parsed TGA results back to elabFTW experiment.

        Updates the experiment body with a summary table, chart, and
        NOMAD link. Sets status to "Success".
        """
        # Build results table
        tg = computed.get("tg_glass_transition", "")
        residue = computed.get("residue_mass_pct", "")
        onset = computed.get("onset_temperature", "")
        td5 = computed.get("mass_loss_5pct", "")
        td10 = computed.get("mass_loss_10pct", "")

        table_rows = ""
        steps = computed.get("steps", [])
        for step in steps:
            table_rows += (
                f"<tr><td>{step.get('onset_temperature', '')} °C</td>"
                f"<td>{step.get('offset_temperature', '')} °C</td>"
                f"<td>{step.get('mass_loss_pct', '')} %</td>"
                f"<td>{step.get('assignment', '')}</td></tr>"
            )

        html_body = f"""<h2>TGA Results: {sample_name}</h2>

<h3>Summary</h3>
<table border="1" style="border-collapse:collapse;width:100%">
<tr style="background:#f0f0f0"><th>Property</th><th>Value</th></tr>
<tr><td>Tg (glass transition)</td><td>{tg}</td></tr>
<tr><td>Residue</td><td>{residue}</td></tr>
<tr><td>Onset temperature</td><td>{onset}</td></tr>
<tr><td>Td5 (5% mass loss)</td><td>{td5}</td></tr>
<tr><td>Td10 (10% mass loss)</td><td>{td10}</td></tr>
</table>

<h3>Mass Loss Steps</h3>
<table border="1" style="border-collapse:collapse;width:100%">
<tr style="background:#f0f0f0"><th>Onset</th><th>Offset</th><th>Mass Loss</th><th>Assignment</th></tr>
{table_rows}
</table>

<h3>NOMAD Entry</h3>
<p><a href="{nomad_url}">{nomad_url}</a></p>
"""

        if plot_svg:
            html_body += f'\n<img src="data:image/svg+xml;base64,{plot_svg}" style="max-width:100%" />\n'

        # Build metadata with structured results
        meta = {
            "nomad_url": nomad_url,
            "nomad_synced": datetime.now(timezone.utc).isoformat(),
            "nomad_results": computed,
        }

        # Get statuses
        statuses = self.get_team_statuses()
        success_id = statuses.get("Success", 123)

        ok = self.update_experiment(
            experiment_id,
            body=html_body,
            metadata=meta,
            status_id=success_id,
            tags=["TGA", "auto-ingested", "results-available"],
        )

        return ok
