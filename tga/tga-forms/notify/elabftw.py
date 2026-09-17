"""Export a measurement into eLabFTW - independent of the installation.

Instance, team and API key are chosen **per user**, not baked into the code, so
the same export targets the lab's own eLabFTW, a university instance such as a
TUM eLabFTW, or somebody's private one. The admin page holds the defaults, and
every requester can override them for themselves.

What is used from the v2 REST API (stable across 4.x to 6.x):

* ``Authorization: <api key>`` as the only credential,
* ``GET  /info`` to check a connection, ``GET /teams`` for the teams a key may
  write to (the team is passed as ``?team=<id>`` when a key spans several),
* ``POST /experiments`` to create, ``POST /experiments/<id>/uploads`` for the
  figure.

Two pitfalls are handled here because they differ between versions: the created
id arrives either in the JSON body or only in the ``Location`` header, and tags
in the create payload are not accepted by older instances, so they are posted
separately as a fallback.

The API key is only ever put into the request header. It is not logged, not
returned to the browser and not stored anywhere except the settings file.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .entry_data import segment_lines, Tuple
from urllib.parse import urlparse, urlunparse

import requests

log = logging.getLogger("tga.elabftw")

DEFAULT_TIMEOUT = 20


def normalize_instance(url: str) -> Tuple[str, str]:
    """Split a user's instance URL into (web base, API base).

    Accepts what people actually paste: with or without scheme, with or without
    the ``/api/v2`` suffix, with a trailing slash. Returns the base for links
    (``https://host``) and the base for calls (``https://host/api/v2``).
    """
    value = (url or "").strip()
    if not value:
        raise ValueError("no eLabFTW instance given")
    if "//" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v2"):
        path = path[: -len("/api/v2")]
    elif path.endswith("/api"):
        path = path[: -len("/api")]
    web = urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")
    return web, web + "/api/v2"


class ElabFTWError(Exception):
    """Any failure talking to eLabFTW, with the instance's own message kept."""


class ElabFTWClient:
    """Small client for one eLabFTW instance and one API key."""

    def __init__(self, instance: str, api_key: str, *, team: str = "",
                 verify_tls: bool = True, timeout: int = DEFAULT_TIMEOUT):
        if not api_key:
            raise ElabFTWError("no API key given")
        self.web_base, self.api_base = normalize_instance(instance)
        self._owner_id: Optional[str] = None
        self.api_key = api_key
        self.team = str(team or "")
        self.verify_tls = bool(verify_tls)
        self.timeout = timeout

    # ── plumbing ────────────────────────────────────────────────────────────
    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"Authorization": self.api_key, "Accept": "application/json"}
        headers.update(extra or {})
        return headers

    def _params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = dict(extra or {})
        if self.team:
            params["team"] = self.team
        return params

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self.api_base + path
        kwargs.setdefault("timeout", self.timeout)
        kwargs["headers"] = self._headers(kwargs.pop("headers", None))
        kwargs["params"] = self._params(kwargs.pop("params", None))
        kwargs["verify"] = self.verify_tls
        try:
            return requests.request(method, url, **kwargs)
        except requests.RequestException as error:
            raise ElabFTWError(f"{type(error).__name__}: {error}") from error

    @staticmethod
    def _explain(response: requests.Response) -> str:
        """Turn an error response into something a human can act on."""
        try:
            payload = response.json()
            message = payload.get("message") or payload.get("detail") or ""
            description = payload.get("description") or ""
        except ValueError:
            message = (response.text or "").strip()[:200]
            description = ""
        text = " ".join(part for part in (message, description) if part) or response.reason
        if response.status_code == 401:
            return f"401 Unauthorized: the API key was rejected ({text})"
        if response.status_code == 403:
            return f"403 Forbidden: the key may not write here ({text})"
        return f"{response.status_code} {text}"

    # ── reading ─────────────────────────────────────────────────────────────
    def info(self) -> Dict[str, Any]:
        response = self._request("GET", "/info")
        if response.status_code != 200:
            raise ElabFTWError(self._explain(response))
        try:
            return response.json()
        except ValueError:
            return {}

    def teams(self) -> List[Dict[str, Any]]:
        response = self._request("GET", "/teams")
        if response.status_code != 200:
            raise ElabFTWError(self._explain(response))
        payload = response.json()
        return payload if isinstance(payload, list) else []

    def test_connection(self) -> Dict[str, Any]:
        """Everything the admin page needs to tell a working setup from a typo."""
        result: Dict[str, Any] = {"ok": False, "instance": self.web_base,
                                  "version": "", "teams": [], "error": ""}
        try:
            info = self.info()
            result["version"] = str(info.get("version") or "")
            try:
                result["teams"] = [f"{t.get('id')}: {t.get('name')}" for t in self.teams()]
            except ElabFTWError as error:
                result["error"] = f"connected, but teams could not be read ({error})"
            result["ok"] = True
        except ElabFTWError as error:
            result["error"] = str(error)
        return result

    # ── writing ─────────────────────────────────────────────────────────────
    def create_experiment(self, title: str, body: str, *,
                          category: Optional[str] = None,
                          tags: Optional[List[str]] = None,
                          metadata: Optional[str] = None) -> Dict[str, Any]:
        """Create an experiment; returns {'id', 'url', 'tags_supported'}."""
        payload: Dict[str, Any] = {"title": title, "body": body}
        if category:
            payload["category"] = category
        if tags:
            payload["tags"] = tags
        if metadata:
            payload["metadata"] = metadata
        response = self._request("POST", "/experiments", json=payload)

        tags_supported = True
        if response.status_code >= 400 and tags:
            # Older instances reject the tags field in the create payload.
            payload.pop("tags", None)
            response = self._request("POST", "/experiments", json=payload)
            tags_supported = False
        if response.status_code not in (200, 201):
            raise ElabFTWError(self._explain(response))

        experiment_id = self._created_id(response)
        if experiment_id and tags and not tags_supported:
            self.add_tags(experiment_id, tags)
        return {"id": experiment_id, "url": self.experiment_url(experiment_id),
                "tags_supported": tags_supported}

    @staticmethod
    def _created_id(response: requests.Response) -> str:
        """The id is in the body on new instances and only in Location on old ones.

        eLabFTW answers a create with ``Location: /api/v2/experiments/123``; the
        JSON body only started carrying ``id`` later, so both are read.
        """
        try:
            payload = response.json()
            if isinstance(payload, dict):
                if payload.get("id"):
                    return str(payload["id"])
                # Some versions wrap the entity: {"experiments": {"id": ...}}
                for value in payload.values():
                    if isinstance(value, dict) and value.get("id"):
                        return str(value["id"])
        except ValueError:
            pass
        location = response.headers.get("Location", "")
        if location:
            return location.rstrip("/").split("/")[-1].split("?")[0]
        return ""

    def owner_id(self) -> str:
        """The userid of the key's owner - needed to move an experiment."""
        if self._owner_id is None:
            response = self._request("GET", "/users/me")
            if response.status_code != 200:
                raise ElabFTWError(self._explain(response))
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            # Nicht jede Instanz antwortet hier mit einem Objekt (ein Stub oder
            # eine aeltere Version kann eine Liste schicken).
            self._owner_id = str(payload.get("userid") or "") \
                if isinstance(payload, dict) else ""
        return self._owner_id

    def move_to_team(self, experiment_id: str, team: str) -> str:
        """Put the experiment into ``team``; returns the team that now holds it.

        eLabFTW's v2 has no team field on create: the experiment lands in the
        team of the key's owner, and the only way to move it is the ownership
        transfer action. It is allowed here because the owner is a member of
        every team the key can list - GET /teams only returns those, which is
        also why the page can offer exactly this list as a choice.
        """
        if not experiment_id or not str(team).strip():
            return ""
        try:
            target_team = int(str(team).strip())
        except ValueError:
            raise ElabFTWError(f"team must be a number, got {team!r}")
        response = self._request(
            "PATCH", f"/experiments/{experiment_id}",
            json={"action": "updateowner", "userid": int(self.owner_id() or 0),
                  "team": target_team})
        if response.status_code >= 400:
            raise ElabFTWError(self._explain(response))
        return str(target_team)

    def add_tags(self, experiment_id: str, tags: List[str]) -> bool:
        """Best effort: a missing tag must not fail an export."""
        for tag in tags:
            try:
                response = self._request("POST", f"/experiments/{experiment_id}/tags",
                                         json={"tag": tag})
                if response.status_code >= 400:
                    return False
            except ElabFTWError:
                return False
        return True

    def upload_attachment(self, experiment_id: str, filename: str, content: bytes,
                          comment: str = "") -> bool:
        """Attach a file (the DTG figure). Returns True on success."""
        files = {"file": (filename, content, "application/octet-stream")}
        data = {"comment": comment} if comment else None
        response = self._request("POST", f"/experiments/{experiment_id}/uploads",
                                 files=files, data=data,
                                 headers={"Content-Type": None})
        if response.status_code in (200, 201):
            return True
        raise ElabFTWError(self._explain(response))

    def experiment_url(self, experiment_id: str) -> str:
        """The link a human opens. Query style, which all versions still serve."""
        if not experiment_id:
            return self.web_base
        return f"{self.web_base}/experiments.php?mode=view&id={experiment_id}"


# ── the entry body ──────────────────────────────────────────────────────────

def _esc(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def experiment_body(ctx: Dict[str, Any]) -> str:
    """HTML body for the eLabFTW experiment: parameters, results, links back.

    Written for someone reading the ELN months later: what was measured, with
    which program, what came out, and where the data lives.
    """
    params = ctx.get("parameters") or {}
    results = ctx.get("results") or {}
    rows = []
    for label, value in (
        ("Sample code", ctx.get("code")),
        ("Sample name", ctx.get("sample_name")),
        ("Requester", ctx.get("requester")),
        ("Measured on", ctx.get("measured_on")),
        ("Operator", ctx.get("operator")),
        ("Atmosphere", params.get("atmosphere")),
        ("Gas flows", params.get("gas_flows")),
        ("Mass spectrometer", params.get("ms_coupling")),
        ("Sample mass", params.get("sample_mass") or results.get("sample_mass")),
        ("Crucible", results.get("pan")),
        ("Mass loss", results.get("mass_loss")),
        ("Onset (Td5)", results.get("td5")),
        ("Onset (Td10)", results.get("td10")),
        ("Residue", results.get("residue")),
    ):
        if value not in (None, ""):
            rows.append(f"<tr><th align='left'>{_esc(label)}</th><td>{_esc(value)}</td></tr>")

    segments = params.get("segments") or []
    program = ""
    if segments:
        items = "".join("<li>" + _esc(line) + "</li>" for line in segment_lines(segments))
        program = "<h3>Temperature program</h3><ol>" + items + "</ol>"

    links = []
    if ctx.get("entry_url"):
        links.append(f"<li>NOMAD entry (all curves and raw data): "
                     f"<a href='{_esc(ctx['entry_url'])}'>{_esc(ctx['entry_url'])}</a></li>")
    if ctx.get("upload_url") and ctx.get("upload_url") != ctx.get("entry_url"):
        links.append(f"<li>NOMAD upload: <a href='{_esc(ctx['upload_url'])}'>"
                     f"{_esc(ctx['upload_url'])}</a></li>")
    if ctx.get("download_url"):
        links.append(f"<li>Download package for the ELN: "
                     f"<a href='{_esc(ctx['download_url'])}'>{_esc(ctx['download_url'])}</a></li>")

    parts = [f"<h2>TGA measurement {_esc(ctx.get('code', ''))} - "
             f"{_esc(ctx.get('sample_name', ''))}</h2>",
             "<p>Exported automatically from the TGA request system.</p>",
             "<table>" + "".join(rows) + "</table>",
             program]
    if links:
        parts.append("<h3>Data</h3><ul>" + "".join(links) + "</ul>")
    if ctx.get("note"):
        parts.append(f"<p>{_esc(ctx['note'])}</p>")
    return "\n".join(part for part in parts if part)


def export_entry(ctx: Dict[str, Any], target: Dict[str, Any], *,
                 figure: Optional[bytes] = None,
                 filename: Optional[str] = None,
                 client: Optional[ElabFTWClient] = None,
                 team: Optional[str] = None) -> Dict[str, Any]:
    """Push one measurement into eLabFTW.

    ``target`` is the user's eLabFTW configuration (instance, API key, team,
    category); the caller resolves it, so this function stays independent of
    where the values came from. ``team`` overrides the configured team for this
    one export (the UI offers a choice).

    Returns a report with the experiment id and URL, or an error string - the
    caller decides what to do with it (the UI shows it, the notification says
    whether the export worked).
    """
    wanted_team = str(team if team is not None else target.get("team", "") or "").strip()
    report: Dict[str, Any] = {"ok": False, "id": "", "url": "", "attached": False,
                              "instance": "", "team": wanted_team,
                              "team_moved": False, "team_error": "", "error": ""}
    instance = (target or {}).get("instance_url", "")
    api_key = (target or {}).get("api_key", "")
    if not instance or not api_key:
        report["error"] = "instance URL or API key missing"
        return report

    try:
        client = client or ElabFTWClient(
            instance, api_key, team=wanted_team,
            verify_tls=bool(target.get("verify_tls", True)))
        report["instance"] = client.web_base
        title = f"TGA {ctx.get('code', '')} - {ctx.get('sample_name', '')}".strip(" -")
        tags = [t for t in ("TGA", ctx.get("code", ""), ctx.get("sample_name", "")) if t]
        created = client.create_experiment(title, experiment_body(ctx),
                                           category=(target.get("category") or None),
                                           tags=tags)
        report["id"] = created["id"]
        report["url"] = created["url"]
        # Das Team setzt eLabFTW beim Anlegen selbst (das des Key-Eigentuemers);
        # nur der Besitzerwechsel kann es danach aendern. Scheitert er, ist das
        # Experiment trotzdem da - also kein Fehlschlag, sondern ein Hinweis.
        if wanted_team:
            try:
                report["team"] = client.move_to_team(created["id"], wanted_team)
                report["team_moved"] = True
            except Exception as error:                  # noqa: BLE001
                # Das Experiment ist angelegt; ein misslungener Teamwechsel ist
                # ein Hinweis, kein Fehlschlag des Exports.
                report["team_error"] = f"{type(error).__name__}: {error}"
                log.warning("experiment %s stays in the owner's team: %s",
                            created["id"], error)
        if figure:
            try:
                client.upload_attachment(created["id"], filename or "dtg_curve.png",
                                         figure, comment="DTG curve (temperature vs DTG)")
                report["attached"] = True
            except ElabFTWError as error:
                log.warning("attachment upload failed: %s", error)
        report["ok"] = True
    except ElabFTWError as error:
        report["error"] = str(error)
    except Exception as error:                     # noqa: BLE001 - never break the caller
        report["error"] = f"{type(error).__name__}: {error}"
    return report


def export_report_json(report: Dict[str, Any]) -> str:
    """Store the report with the entry - small, and free of the API key."""
    return json.dumps({k: v for k, v in report.items() if k != "api_key"},
                      ensure_ascii=False, sort_keys=True)
