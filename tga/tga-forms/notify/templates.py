"""The notification texts.

English on purpose: they go to operators, requesters and outside collaborators,
and the lab works in English.

Each builder returns ``(subject, text, html)``. The plain text version carries
every fact on its own - HTML only adds links and bold text for the two cases
where a mail client shows it, so nothing is lost in a text-only reader.

Style rules kept from the form app: no em dashes, short sentences, the concrete
action first (what to write on the sample, where to bring it, which link to
open).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .entry_data import segment_lines

Message = tuple          # (subject, text, html)


def _line(label: str, value: Any) -> str:
    return f"{label}: {value}" if value not in (None, "") else ""


def _parameter_lines(params: Optional[Dict[str, Any]]) -> List[str]:
    """The parameter overview both the operator and the requester get.

    The operator reads this to set the instrument up, the requester to check the
    submission - same list, so a disagreement is visible in the same words.
    """
    params = params or {}
    lines: List[str] = []
    for label, value in (
        ("Atmosphere", params.get("atmosphere")),
        ("Gas flows", params.get("gas_flows")),
        ("Mass spectrometer", params.get("ms_coupling")),
        ("Sample mass", params.get("sample_mass")),
        ("Estimated run time", params.get("runtime")),
    ):
        text = _line(label, value)
        if text:
            lines.append(text)

    segments = params.get("segments") or []
    if segments:
        program = ["Temperature program"] + [
            "  " + line for line in segment_lines(segments)]
        lines.append("\n".join(program))
    # Liste zurueckgeben, nicht einen fertigen Text: der Aufrufer haengt die
    # Bloecke selbst zusammen (ein zurueckgegebener String wurde hier schon
    # einmal Zeichen fuer Zeichen ausgegeben).
    return [line for line in lines if line]


def _esc(value: Any) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _html(subject: str, paragraphs: List[str], bullets: Optional[List[str]] = None,
          action: Optional[Dict[str, str]] = None,
          action_label: str = "") -> str:
    """Small HTML body: paragraphs, an optional list, one button-like link."""
    parts = [f"<h2>{_esc(subject)}</h2>"]
    parts += [f"<p>{_esc(p)}</p>" for p in paragraphs if p]
    if bullets:
        parts.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>")
    if action:
        for label, url in action.items():
            parts.append(f'<p><a href="{_esc(url)}">{_esc(label)}</a></p>')
    parts.append('<hr><p style="color:#666;font-size:12px">'
                 'Automatic message from the TGA request system. '
                 'Please do not reply to the operator address directly, '
                 'use the contacts listed above.</p>')
    return "\n".join(parts)


def _contacts_text(contacts: Optional[Dict[str, str]]) -> str:
    contacts = contacts or {}
    pedro = contacts.get("pedro") or contacts.get("consultation", "")
    luca = contacts.get("luca") or ""
    lines = []
    if pedro:
        lines.append(f"  Pedro Braun: {pedro}")
    if luca:
        lines.append(f"  Luca Reichert: {luca}")
    return "\n".join(lines)


# ── request created ─────────────────────────────────────────────────────────

def request_created_operator(ctx: Dict[str, Any]) -> Message:
    """Goes to the operators: what to write on the sample and how it is set up."""
    code = ctx.get("code", "")
    sample = ctx.get("sample_name", "")
    subject = f"[TGA] New request {code} - {sample}".strip()
    params = _parameter_lines(ctx.get("parameters"))
    consultation = ctx.get("consultation") or []

    text_lines = [
        f"A new TGA request was submitted and is waiting for measurement.",
        "",
        f"Sample code: {code}",
        f"Write this code on the sample and on the crucible.",
        f"Sample name: {sample}",
        f"Requester: {ctx.get('requester', '')} <{ctx.get('requester_email', '')}>",
        "",
        "Parameters",
        *params,
    ]
    if consultation:
        text_lines += ["", "Needs agreement with the lab before it runs",
                       *[f"  - {reason}" for reason in consultation]]
    if ctx.get("drop_off"):
        text_lines += ["", "Sample drop-off (agreed by email)", ctx.get("drop_off", "")]
    text_lines += ["", "NOMAD entry", ctx.get("entry_url", "")]
    action = {"Open the NOMAD entry": ctx.get("entry_url", "")} if ctx.get("entry_url") else None
    html = _html(subject, [
        "A new TGA request was submitted and is waiting for measurement.",
        f"Write sample code {code} on the sample and on the crucible.",
        f"Requester: {ctx.get('requester', '')} <{ctx.get('requester_email', '')}>",
    ], bullets=params, action=action)
    return subject, "\n".join(text_lines), html


def request_created_user(ctx: Dict[str, Any]) -> Message:
    """Goes to the requester: what to write on the sample, where to bring it."""
    code = ctx.get("code", "")
    sample = ctx.get("sample_name", "")
    subject = f"[TGA] Request received: {sample} ({code})".strip()
    params = _parameter_lines(ctx.get("parameters"))
    contacts = ctx.get("contacts") or {}

    text_lines = [
        "Your TGA request was submitted.",
        "",
        f"Sample code: {code}",
        f"Write this code on the sample you hand in, so it can be matched to this request.",
        "",
        "Next step",
        "Agree the drop-off with the lab by email before you bring the sample in:",
        _contacts_text(contacts) or "  (contacts are not configured yet)",
        "",
        "Drop-off address",
        ctx.get("drop_off", ""),
        "",
        "Your parameters",
        *params,
    ]
    if ctx.get("consultation"):
        text_lines += ["", "The lab has to confirm these points before the measurement:",
                       *[f"  - {reason}" for reason in ctx.get("consultation")]]
    text_lines += ["", "NOMAD entry", ctx.get("entry_url", "")]
    action = {"Open your request in NOMAD": ctx.get("entry_url", "")} if ctx.get("entry_url") else None
    html = _html(subject, [
        f"Your TGA request for {sample} was submitted.",
        f"Write sample code {code} on the sample you hand in.",
        "Agree the drop-off with the lab by email before you bring the sample in.",
        "Drop-off: " + (ctx.get("drop_off") or "").replace("\n", ", "),
    ], bullets=params, action=action)
    return subject, "\n".join(text_lines), html


# ── results ready ───────────────────────────────────────────────────────────

def _result_lines(results: Optional[Dict[str, Any]]) -> List[str]:
    results = results or {}
    lines = []
    for label, key in (("Mass loss", "mass_loss"),
                       ("Onset (Td5)", "td5"),
                       ("Onset (Td10)", "td10"),
                       ("Residue", "residue"),
                       ("Sample mass", "sample_mass"),
                       ("Crucible", "pan")):
        text = _line(label, results.get(key))
        if text:
            lines.append(text)
    return lines


def results_ready_user(ctx: Dict[str, Any]) -> Message:
    """Goes to the requester: the measurement is done, here is how to get it."""
    sample = ctx.get("sample_name", "")
    code = ctx.get("code", "")
    subject = f"[TGA] Results ready: {sample} ({code})".strip()
    results = _result_lines(ctx.get("results"))
    eln_action = {}
    if ctx.get("elabftw_url"):
        eln_action["Open the entry in eLabFTW"] = ctx["elabftw_url"]
    elif ctx.get("elabftw_instance"):
        eln_action["Open your eLabFTW"] = ctx["elabftw_instance"]
    if ctx.get("download_url"):
        eln_action["Download the data package"] = ctx["download_url"]

    text_lines = [
        "The measurement of your sample is finished.",
        "",
        f"Sample code: {code}",
        f"Sample name: {sample}",
        "",
        "Results",
        *results,
        "",
        "Curves and raw data",
        "The NOMAD entry has the mass and DTG curves, the cleaned DTG curve and "
        "all result values.",
        ctx.get("entry_url", ""),
        "",
        "Take it into your ELN",
    ]
    if ctx.get("elabftw_url"):
        text_lines.append(f"  The entry was pushed to eLabFTW: {ctx['elabftw_url']}")
    else:
        text_lines.append("  Push the entry to your eLabFTW from the request page "
                          "(choose your instance, team and API key there).")
    if ctx.get("requests_url"):
        text_lines.append(f"  Your requests: {ctx['requests_url']}")
    if ctx.get("download_url"):
        text_lines.append(f"  Or download the package for a manual upload: {ctx['download_url']}")
    text_lines += ["", "Questions about the measurement",
                   _contacts_text(ctx.get("contacts")) or "  (contacts are not configured yet)"]
    action = dict(eln_action)
    if ctx.get("entry_url"):
        action["Open the entry in NOMAD"] = ctx["entry_url"]
    html = _html(subject, [
        f"The measurement of {sample} is finished.",
        "The curves and every result value are in the NOMAD entry.",
        "You can pull the entry into your ELN from the request page, or download "
        "the data package for a manual upload.",
    ], bullets=results, action=action)
    return subject, "\n".join(text_lines), html


def results_ready_operator(ctx: Dict[str, Any]) -> Message:
    """Short note to the operators: the run is processed and in NOMAD."""
    sample = ctx.get("sample_name", "")
    code = ctx.get("code", "")
    subject = f"[TGA] Processed: {sample} ({code})".strip()
    text_lines = [
        "The measurement was processed automatically.",
        "",
        f"Sample code: {code}",
        f"Sample name: {sample}",
        _line("Residue", (ctx.get("results") or {}).get("residue")),
        "",
        "NOMAD entry",
        ctx.get("entry_url", ""),
    ]
    action = {"Open the NOMAD entry": ctx.get("entry_url", "")} if ctx.get("entry_url") else None
    html = _html(subject, ["The measurement was processed automatically."],
                 bullets=_result_lines(ctx.get("results")), action=action)
    return subject, "\n".join([line for line in text_lines if line is not None]), html


def processing_failed_operator(ctx: Dict[str, Any]) -> Message:
    """A run could not be processed - the operators have to look at the file."""
    # Der Betreff muss auch dann etwas sagen, wenn kein Datei- und kein
    # Probenname bekannt ist: eine leere Betreffzeile faellt im Postfach nicht auf.
    what = ctx.get("filename") or ctx.get("sample_name") or ctx.get("code") or "unknown file"
    subject = f"[TGA] Processing failed: {what}".strip()
    text_lines = [
        "The automatic processing of a measurement failed.",
        "",
        _line("File", ctx.get("filename")),
        _line("Sample", ctx.get("sample_name")),
        _line("Error", ctx.get("error")),
        "",
        "Upload in NOMAD",
        ctx.get("upload_url", "") or ctx.get("entry_url", ""),
    ]
    action = {"Open the upload": ctx.get("upload_url", "")} if ctx.get("upload_url") else None
    html = _html(subject, ["The automatic processing of a measurement failed.",
                           f"Error: {ctx.get('error', '')}"], action=action)
    return subject, "\n".join(text_lines), html


def moved_to_elabftw(ctx: Dict[str, Any]) -> Message:
    """Confirmation that the entry was pushed into an ELN."""
    sample = ctx.get("sample_name", "")
    subject = f"[TGA] Exported to eLabFTW: {sample} ({ctx.get('code', '')})".strip()
    text_lines = [
        "The measurement was exported to eLabFTW.",
        "",
        _line("Sample", sample),
        _line("Instance", ctx.get("elabftw_instance")),
        _line("Team", ctx.get("elabftw_team")),
        _line("Experiment", ctx.get("elabftw_url")),
        _line("Exported by", ctx.get("exported_by")),
        "",
        "NOMAD entry",
        ctx.get("entry_url", ""),
    ]
    action = {}
    if ctx.get("elabftw_url"):
        action["Open the eLabFTW experiment"] = ctx["elabftw_url"]
    if ctx.get("entry_url"):
        action["Open the NOMAD entry"] = ctx["entry_url"]
    html = _html(subject, ["The measurement was exported to eLabFTW."],
                 bullets=[f"Instance: {ctx.get('elabftw_instance', '')}",
                          f"Experiment: {ctx.get('elabftw_url', '')}"],
                 action=action or None)
    return subject, "\n".join(text_lines), html


BUILDERS = {
    "request_created_operator": request_created_operator,
    "request_created_user": request_created_user,
    "results_ready_user": results_ready_user,
    "results_ready_operator": results_ready_operator,
    "processing_failed_operator": processing_failed_operator,
    "moved_to_elabftw": moved_to_elabftw,
}

# Who gets which event. "operators" is the list from the settings, "requester"
# is the address stored with the request.
DEFAULT_AUDIENCE = {
    "request_created_operator": "operators",
    "request_created_user": "requester",
    "results_ready_user": "requester",
    "results_ready_operator": "operators",
    "processing_failed_operator": "operators",
    "moved_to_elabftw": "requester",
}
