"""elabFTW API client for instrument data pipeline.

Handles:
- Searching for experiments by sample name
- Patching experiment body with results
- Uploading processed data files
- Setting experiment status (Running/Success/Error)
- FIFO matching of queued experiments
- Linking back NOMAD URL
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
        params = {"team": self.team, "q": sample_name, "limit": 10}
        if category_id:
            params["category"] = category_id
        try:
            resp = self.session.get(f"{self.api_url}/experiments", params=params, timeout=self.timeout)
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    for exp in results:
                        if exp.get("title", "").lower() == sample_name.lower():
                            return exp
                    return results[0]
        except requests.RequestException:
            pass
        return None

    def find_experiments_by_status(self, status_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(
                f"{self.api_url}/experiments",
                params={"team": self.team, "status": status_id, "limit": limit},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return []

    def get_experiment(self, experiment_id: int) -> Optional[Dict[str, Any]]:
        try:
            resp = self.session.get(f"{self.api_url}/experiments/{experiment_id}", timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def update_experiment(
        self, experiment_id: int,
        body: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
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
                f"{self.api_url}/experiments/{experiment_id}", json=payload, timeout=self.timeout,
            )
            return resp.status_code in (200, 201, 204, 301, 302)
        except requests.RequestException:
            return False

    def upload_file(self, experiment_id: int, filepath: str) -> bool:
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
        try:
            resp = self.session.post(
                f"{self.api_url}/experiments/{experiment_id}/experiments_links",
                json={"link_id": item_id, "link_type": "item"},
                timeout=self.timeout,
            )
            return resp.status_code in (200, 201, 204)
        except requests.RequestException:
            return False

    # ── Items ───────────────────────────────────────────────────────────────

    def create_item(
        self,
        title: str,
        body: str = "",
        tags: Optional[List[str]] = None,
        status_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {"title": title, "team": self.team}
        if body:
            payload["body"] = body
        if tags:
            payload["tags"] = tags
        if status_id:
            payload["status"] = status_id
        if metadata:
            payload["metadata"] = json.dumps(metadata)
        try:
            resp = self.session.post(f"{self.api_url}/items", json=payload, timeout=self.timeout)
            return resp.json() if resp.status_code == 200 else None
        except requests.RequestException:
            return None

    def get_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        try:
            resp = self.session.get(f"{self.api_url}/items/{item_id}", timeout=self.timeout)
            return resp.json() if resp.status_code == 200 else None
        except requests.RequestException:
            return None

    def update_item(
        self, item_id: int,
        body: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
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
            resp = self.session.patch(f"{self.api_url}/items/{item_id}", json=payload, timeout=self.timeout)
            return resp.status_code in (200, 201, 204, 301, 302)
        except requests.RequestException:
            return False

    def find_items_by_status(self, status_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(
                f"{self.api_url}/items",
                params={"team": self.team, "status": status_id, "limit": limit},
                timeout=self.timeout,
            )
            return resp.json() if resp.status_code == 200 else []
        except requests.RequestException:
            return []

    def find_item_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            resp = self.session.get(
                f"{self.api_url}/items",
                params={"team": self.team, "q": name, "limit": 10},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                results = resp.json()
                for item in results:
                    if item.get("title", "").lower() == name.lower():
                        return item
                return results[0] if results else None
        except requests.RequestException:
            pass
        return None

    def upload_file_to_item(self, item_id: int, filepath: str) -> Optional[Dict[str, Any]]:
        """Upload a file to an item and return the upload metadata, or None on failure."""
        try:
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                resp = requests.post(
                    f"{self.api_url}/items/{item_id}/uploads",
                    headers={"Authorization": self.api_key},
                    files=files,
                    timeout=self.timeout * 2,
                )
            if resp.status_code in (200, 201, 204):
                if resp.text:
                    return resp.json()
                return {"real_name": filename}  # fallback if no response body
        except (requests.RequestException, IOError):
            pass
        return None

    # ── Item FIFO matching ─────────────────────────────────────────────────

    def find_oldest_queued_tga_item(self, ready_status_id: int = 67) -> Optional[Dict[str, Any]]:
        """Find the oldest 'Ready' TGA item without results (FIFO)."""
        items = self.find_items_by_status(ready_status_id, limit=50)
        if not items:
            return None
        candidates = []
        for item in items:
            meta = item.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict) and meta.get("nomad_results"):
                continue
            candidates.append(item)
        if not candidates:
            return None
        candidates.sort(key=lambda e: e.get("created_at", ""))
        return candidates[0]

    # ── Item status helpers ────────────────────────────────────────────────

    def get_item_statuses(self) -> Dict[str, int]:
        try:
            resp = self.session.get(
                f"{self.api_url}/teams/{self.team}/items_status",
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return {s["title"]: s["id"] for s in resp.json()}
        except requests.RequestException:
            pass
        return {}

    def set_item_running(self, item_id: int, running_status_id: int = 72) -> bool:
        return self.update_item(item_id, status_id=running_status_id)

    def set_item_error_status(self, item_id: int, msg: str, error_status_id: int = 68) -> bool:
        """Set item to 'Please check' (68) with error message."""
        html = "<h2>Pipeline Error</h2><pre>" + msg + "</pre>"
        return self.update_item(item_id, body=html, status_id=error_status_id)

    # ── Item result push-back ──────────────────────────────────────────────

    def push_tga_results_to_item(
        self,
        item_id: int,
        sample_name: str,
        signals: Dict[str, List[float]],
        computed: Dict[str, Any],
        nomad_url: str,
        plot_url: str = "",
    ) -> bool:
        """Push parsed TGA results back to a TGA item (not experiment)."""
        # Same HTML body generation as push_tga_results (reuses _build_raw_data_table)
        tg = computed.get("tg_glass_transition", "")
        residue = computed.get("residue_mass_pct", "")
        onset = computed.get("onset_temperature", "")
        td5 = computed.get("mass_loss_5pct", "")
        td10 = computed.get("mass_loss_10pct", "")
        dtg_max = computed.get("dtg_max", "")
        steps = computed.get("steps", [])

        def _card(label, value, unit, color):
            v = f"{value}" if value else "\u2014"
            return (
                f'<div style="background:{color}10;border-left:4px solid {color};border-radius:4px;'
                f'padding:10px 14px;margin:4px;flex:1;min-width:120px">'
                f'<div style="font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px">{label}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#333;margin:2px 0">{v}</div>'
                f'<div style="font-size:11px;color:#888">{unit}</div></div>'
            )

        cards_parts = []
        if tg: cards_parts.append(_card("Tg (Glass Transition)", tg, "\u00b0C", "#2196F3"))
        if onset: cards_parts.append(_card("Onset Temperature", onset, "\u00b0C", "#FF9800"))
        if residue: cards_parts.append(_card("Residue", residue, "%", "#4CAF50"))
        if td5: cards_parts.append(_card("Td5 (5% Loss)", td5, "\u00b0C", "#9C27B0"))
        if td10: cards_parts.append(_card("Td10 (10% Loss)", td10, "\u00b0C", "#E91E63"))
        if dtg_max: cards_parts.append(_card("Max DTG Rate", dtg_max, "%/min", "#607D8B"))
        summary_cards = "".join(cards_parts)

        # Steps table
        if steps:
            step_rows = []
            colors = ["#E3F2FD", "#FFF3E0", "#E8F5E9", "#F3E5F5", "#FFEBEE", "#ECEFF1"]
            for i, step in enumerate(steps):
                bg = colors[i % len(colors)]
                step_rows.append(
                    f'<tr style="background:{bg}">'
                    f'<td style="padding:6px 10px;font-weight:600">{step.get("onset_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px">{step.get("offset_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px">{step.get("peak_dtg_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px;font-weight:600">{step.get("mass_loss_pct", "")} %</td>'
                    f'<td style="padding:6px 10px;color:#555">{step.get("assignment", "")}</td></tr>'
                )
            steps_html = (
                '<h3 style="margin:16px 0 8px">Mass Loss Steps</h3>'
                '<table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e0e0e0">'
                '<thead><tr style="background:#f5f5f5;border-bottom:2px solid #ddd">'
                '<th style="padding:8px 10px;text-align:left">Onset</th>'
                '<th style="padding:8px 10px;text-align:left">Offset</th>'
                '<th style="padding:8px 10px;text-align:left">DTG Peak</th>'
                '<th style="padding:8px 10px;text-align:left">Mass Loss</th>'
                '<th style="padding:8px 10px;text-align:left">Assignment</th></tr></thead>'
                f'<tbody>{"".join(step_rows)}</tbody></table>'
            )
        else:
            steps_html = ""

        # Progress bar
        progress_html = ""
        if residue:
            try:
                res_pct = float(residue)
                loss_pct = 100.0 - res_pct
                progress_html = (
                    '<h3 style="margin:16px 0 8px">Mass Balance</h3>'
                    '<table style="border-collapse:collapse;width:100%"><tr>'
                    f'<td style="width:{loss_pct:.1f}%;background:#E91E63;padding:4px 0;text-align:center;color:#fff;font-size:12px;font-weight:600">{loss_pct:.1f}%</td>'
                    f'<td style="width:{res_pct:.1f}%;background:#4CAF50;padding:4px 0;text-align:center;color:#fff;font-size:12px;font-weight:600">{res_pct:.1f}%</td>'
                    '</tr></table>'
                    '<p style="font-size:12px;color:#666;margin:4px 0">Mass loss (red) / Residue (green)</p>'
                )
            except (ValueError, TypeError):
                pass

        # Raw data
        raw_html = self._build_raw_data_table(signals)

        # Collapsible
        collapsible_html = (
            '<div style="margin:16px 0">'
            '<details><summary style="cursor:pointer;font-weight:700;font-size:15px;color:#1976D2;padding:4px 0">'
            "\U0001f4ca Raw Measurement Data "
            '<span style="font-weight:400;color:#888;font-size:12px">(click to expand)</span></summary>'
            f'<div style="margin-top:8px">{raw_html}</div></details></div>'
        )
        # Plot note — embed the uploaded plot as an image
        if plot_url:
            plot_html = (
                f'<img src="{plot_url}" style="max-width:100%;border:1px solid #e0e0e0;border-radius:4px;margin:10px 0" />'
            )
        else:
            plot_html = ""


        # NOMAD link
        nomad_html = ""
        if nomad_url:
            nomad_html = (
                '<h3 style="margin:16px 0 8px">NOMAD Entry</h3>'
                f'<p><a href="{nomad_url}" target="_blank" style="color:#1976D2">{nomad_url}</a></p>'
            )

        # Assemble
        html_body = (
            '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:900px">'
            '<h2 style="color:#333;border-bottom:2px solid #1976D2;padding-bottom:8px">'
            f"\U0001f52c TGA Results: {sample_name}</h2>"
            f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin:12px 0">{summary_cards}</div>'
            f"{progress_html}"
            f"{steps_html}"
            f"{plot_html}"
            f"{nomad_html}"
            f"{collapsible_html}"
            "</div>"
        )

        meta = {
            "nomad_url": nomad_url,
            "nomad_synced": datetime.now(timezone.utc).isoformat(),
            "nomad_results": computed,
        }
        # Preserve extra_fields from the original item
        existing = self.get_item(item_id)
        if existing:
            emeta = existing.get("metadata", "")
            if isinstance(emeta, str) and emeta:
                try:
                    ed = json.loads(emeta)
                    if "extra_fields" in ed:
                        meta["extra_fields"] = ed["extra_fields"]
                except Exception:
                    pass

        # Update item (body + metadata)
        return self.update_item(
            item_id,
            body=html_body,
            metadata=meta,
        )

    # ── Experiment FIFO matching (kept for backward compat) ────────────────

    def find_oldest_queued_experiment(self) -> Optional[Dict[str, Any]]:
        statuses = self.get_team_statuses()
        running_id = statuses.get("Running")
        if not running_id:
            return None
        exps = self.find_experiments_by_status(running_id, limit=50)
        if not exps:
            return None
        candidates = []
        for exp in exps:
            meta = exp.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict) and meta.get("nomad_results"):
                continue
            candidates.append(exp)
        if not candidates:
            return None
        candidates.sort(key=lambda e: e.get("created_at", ""))
        return candidates[0]

    # ── Status helpers ───────────────────────────────────────────────────────

    def get_team_statuses(self) -> Dict[str, int]:
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

    def set_running(self, experiment_id: int) -> bool:
        s = self.get_team_statuses()
        rid = s.get("Running")
        if not rid:
            return False
        return self.update_experiment(experiment_id, status_id=rid)

    def set_error_status(self, experiment_id: int, msg: str) -> bool:
        s = self.get_team_statuses()
        eid = s.get("Error")
        if not eid:
            eid = s.get("Fail")
        if not eid:
            return False
        html = "<h2>Pipeline Error</h2><pre>" + msg + "</pre>"
        return self.update_experiment(experiment_id, body=html, status_id=eid)

    # ── Result push-back ────────────────────────────────────────────────────

    def _build_raw_data_table(self, signals: Dict[str, List[float]], max_rows: int = 20) -> str:
        if not signals:
            return "<p>No raw data available.</p>"
        col_map = {
            "time": "Time (min)",
            "temperature": "Temp (°C)",
            "weight": "Weight (mg)",
            "weight_pct": "Weight (%)",
            "dta": "DTA (°C)",
            "purge_flow": "Purge Flow (mL/min)",
            "storage_modulus": "Storage Modulus (MPa)",
            "loss_modulus": "Loss Modulus (MPa)",
            "tan_delta": "Tan δ",
        }
        cols = [k for k in col_map if k in signals and len(signals[k]) > 0]
        if not cols:
            return "<p>No raw data available.</p>"
        n = len(signals[cols[0]])
        thead = "<tr>" + "".join(f"<th>{col_map[c]}</th>" for c in cols) + "</tr>"
        show_rows = []
        if n <= max_rows + 5:
            show_rows = list(range(n))
        else:
            show_rows = list(range(max_rows))
            show_rows.append("...")
            show_rows.extend(range(n - 5, n))
        tbody_rows = []
        span = len(cols)
        for idx in show_rows:
            if idx == "...":
                tbody_rows.append(
                    f'<tr><td colspan="{span}" style="text-align:center;color:#888;font-style:italic">'
                    f"\u2026 {n - max_rows - 5} more data points (total: {n}) \u2026</td></tr>"
                )
            else:
                cells = []
                for c in cols:
                    val = signals[c][idx]
                    if isinstance(val, float):
                        cells.append(f"<td>{val:.4f}</td>")
                    else:
                        cells.append(f"<td>{val}</td>")
                tbody_rows.append("<tr>" + "".join(cells) + "</tr>")
        return (
            '<div style="border:1px solid #ddd;border-radius:4px;margin:10px 0">'
            '<table style="border-collapse:collapse;width:100%;font-size:12px;font-family:monospace">'
            f'<thead style="background:#f5f5f5;border-bottom:2px solid #ddd">{thead}</thead>'
            f"<tbody>{''.join(tbody_rows)}</tbody></table></div>"
            f'<p style="color:#888;font-size:11px;margin:0">Showing {min(n, max_rows + 5)} of {n} data points</p>'
        )

    def push_tga_results(
        self,
        experiment_id: int,
        sample_name: str,
        signals: Dict[str, List[float]],
        computed: Dict[str, Any],
        nomad_url: str,
        plot_svg: Optional[str] = None,
    ) -> bool:
        tg = computed.get("tg_glass_transition", "")
        residue = computed.get("residue_mass_pct", "")
        onset = computed.get("onset_temperature", "")
        td5 = computed.get("mass_loss_5pct", "")
        td10 = computed.get("mass_loss_10pct", "")
        dtg_max = computed.get("dtg_max", "")
        steps = computed.get("steps", [])

        # --- Summary cards ---
        def _card(label, value, unit, color):
            v = f"{value}" if value else "\u2014"
            return (
                f'<div style="background:{color}10;border-left:4px solid {color};border-radius:4px;'
                f'padding:10px 14px;margin:4px;flex:1;min-width:120px">'
                f'<div style="font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.5px">{label}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#333;margin:2px 0">{v}</div>'
                f'<div style="font-size:11px;color:#888">{unit}</div></div>'
            )

        cards_parts = []
        if tg:
            cards_parts.append(_card("Tg (Glass Transition)", tg, "\u00b0C", "#2196F3"))
        if onset:
            cards_parts.append(_card("Onset Temperature", onset, "\u00b0C", "#FF9800"))
        if residue:
            cards_parts.append(_card("Residue", residue, "%", "#4CAF50"))
        if td5:
            cards_parts.append(_card("Td5 (5% Loss)", td5, "\u00b0C", "#9C27B0"))
        if td10:
            cards_parts.append(_card("Td10 (10% Loss)", td10, "\u00b0C", "#E91E63"))
        if dtg_max:
            cards_parts.append(_card("Max DTG Rate", dtg_max, "%/min", "#607D8B"))
        summary_cards = "".join(cards_parts)

        # --- Mass loss steps table ---
        if steps:
            step_rows = []
            colors = ["#E3F2FD", "#FFF3E0", "#E8F5E9", "#F3E5F5", "#FFEBEE", "#ECEFF1"]
            for i, step in enumerate(steps):
                bg = colors[i % len(colors)]
                step_rows.append(
                    f'<tr style="background:{bg}">'
                    f'<td style="padding:6px 10px;font-weight:600">{step.get("onset_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px">{step.get("offset_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px">{step.get("peak_dtg_temperature", "")} \u00b0C</td>'
                    f'<td style="padding:6px 10px;font-weight:600">{step.get("mass_loss_pct", "")} %</td>'
                    f'<td style="padding:6px 10px;color:#555">{step.get("assignment", "")}</td></tr>'
                )
            steps_html = (
                '<h3 style="margin:16px 0 8px">Mass Loss Steps</h3>'
                '<table style="border-collapse:collapse;width:100%;font-size:13px;border:1px solid #e0e0e0">'
                '<thead><tr style="background:#f5f5f5;border-bottom:2px solid #ddd">'
                '<th style="padding:8px 10px;text-align:left">Onset</th>'
                '<th style="padding:8px 10px;text-align:left">Offset</th>'
                '<th style="padding:8px 10px;text-align:left">DTG Peak</th>'
                '<th style="padding:8px 10px;text-align:left">Mass Loss</th>'
                '<th style="padding:8px 10px;text-align:left">Assignment</th></tr></thead>'
                f'<tbody>{"".join(step_rows)}</tbody></table>'
            )
        else:
            steps_html = ""

        # --- Progress bar for mass balance (simple, sanitizer-safe) ---
        progress_html = ""
        if residue:
            try:
                res_pct = float(residue)
                loss_pct = 100.0 - res_pct
                progress_html = (
                    '<h3 style="margin:16px 0 8px">Mass Balance</h3>'
                    '<table style="border-collapse:collapse;width:100%">'
                    '<tr>'
                    f'<td style="width:{loss_pct:.1f}%;background:#E91E63;padding:4px 0;text-align:center;color:#fff;font-size:12px;font-weight:600">{loss_pct:.1f}%</td>'
                    f'<td style="width:{res_pct:.1f}%;background:#4CAF50;padding:4px 0;text-align:center;color:#fff;font-size:12px;font-weight:600">{res_pct:.1f}%</td>'
                    '</tr>'
                    '</table>'
                    '<p style="font-size:12px;color:#666;margin:4px 0">Mass loss (red) / Residue (green)</p>'
                )
            except (ValueError, TypeError):
                pass

        # --- Raw data ---
        raw_html = self._build_raw_data_table(signals)

        # --- Plot note (image uploaded as file attachment) ---
        plot_html = ""
        if plot_svg:
            plot_html = (
                '<h3 style="margin:16px 0 8px">TGA Plot</h3>'
                '<p style="font-size:13px;color:#555">📊 TGA curve plot available as file attachment <strong>TGA_Plot.png</strong></p>'
            )

        # --- Collapsible raw data ---
        collapsible_html = (
            '<div style="margin:16px 0">'
            '<details><summary style="cursor:pointer;font-weight:700;font-size:15px;color:#1976D2;padding:4px 0">'
            "\U0001f4ca Raw Measurement Data "
            '<span style="font-weight:400;color:#888;font-size:12px">(click to expand)</span></summary>'
            f'<div style="margin-top:8px">{raw_html}</div></details></div>'
        )

        # --- Plot note ---
        plot_html = (
            '<h3 style="margin:16px 0 8px">TGA Plot</h3>'
            '<p style="font-size:13px;color:#555">📊 TGA curve plot available as file attachment <strong>TGA_Plot.png</strong></p>'
        )

        # --- NOMAD link ---
        nomad_html = ""
        if nomad_url:
            nomad_html = (
                '<h3 style="margin:16px 0 8px">NOMAD Entry</h3>'
                f'<p><a href="{nomad_url}" target="_blank" style="color:#1976D2">{nomad_url}</a></p>'
            )

        # --- Assemble ---
        html_body = (
            "<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:900px\">"
            '<h2 style="color:#333;border-bottom:2px solid #1976D2;padding-bottom:8px">'
            f"\U0001f52c TGA Results: {sample_name}</h2>"
            f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin:12px 0">{summary_cards}</div>'
            f"{progress_html}"
            f"{steps_html}"
            f"{plot_html}"
            f"{nomad_html}"
            f"{collapsible_html}"
            "</div>"
        )

        meta = {
            "nomad_url": nomad_url,
            "nomad_synced": datetime.now(timezone.utc).isoformat(),
            "nomad_results": computed,
        }
        statuses = self.get_team_statuses()
        success_id = statuses.get("Success", 123)
        ok = self.update_experiment(
            experiment_id,
            body=html_body,
            metadata=meta,
            status_id=success_id,
        )
        # elabFTW API rejects tags combined with other fields — set separately
        if ok:
            self.update_experiment(
                experiment_id,
                tags=["TGA", "auto-ingested", "results-available"],
            )
        return ok
