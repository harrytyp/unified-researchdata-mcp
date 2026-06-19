"""FastAPI app: registration UI + shared R worker proxy."""

import asyncio
import json
import httpx
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import HTMLResponse, Response

from .jwt_token import encode_token, decode_token
from .r_worker import SharedRWorker

logger = logging.getLogger("elabmcp-proxy.app")

# ── Rate limiting ──
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ── Shared R worker (one process, all users) ──
r_worker = SharedRWorker()

# ── Audit logging ──
_audit_log_path = os.environ.get("ELABMCP_AUDIT_LOG", "/var/log/elabmcp-proxy/audit.log")
_audit_log_dir = os.path.dirname(_audit_log_path)
if _audit_log_dir and not os.path.exists(_audit_log_dir):
    try:
        os.makedirs(_audit_log_dir, exist_ok=True)
    except OSError:
        pass

_audit_logger = logging.getLogger("elabmcp-proxy.audit")
_audit_handler = logging.FileHandler(_audit_log_path, delay=True)
_audit_handler.setFormatter(logging.Formatter(
    "%(asctime)s\t%(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
))
_audit_logger.addHandler(_audit_handler)
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False


def _audit(event: str, **kwargs):
    parts = [event]
    for k, v in sorted(kwargs.items()):
        parts.append(f"{k}={v}")
    _audit_logger.info("\t".join(parts))


# ── Auth helper ──

def _get_creds_and_profile_from_jwt(token: str) -> tuple[str, str, str, list | None] | None:
    """Decode JWT and return (api_key, base_url, profile, enabled_tools) or None."""
    payload = decode_token(token)
    if payload is None:
        return None
    profile = payload.get("p", "r")
    enabled_tools = payload.get("t")
    if profile not in ("r", "h", "f"):
        profile = "r"
    return payload["k"], payload["u"], profile, enabled_tools
_shared_http = None


async def _get_http():
    global _shared_http
    if _shared_http is None:
        _shared_http = httpx.AsyncClient(verify=False, timeout=15.0, limits=httpx.Limits(max_keepalive_connections=10))
    return _shared_http


async def _validate_elabftw_key(base_url: str, api_key: str) -> dict:
    """Validate an elabFTW API key and check write capability."""
    result = {"valid": False, "user": None, "can_write": False, "error": None}
    url = base_url.rstrip("/") + "/api/v2"
    headers = {"Authorization": api_key}
    try:
        client = await _get_http()
        resp = await client.get(f"{url}/users/me", headers=headers)
        if resp.status_code != 200:
            result["error"] = f"API key rejected (HTTP {resp.status_code}). Check your key and base URL."
            return result
        user = resp.json()
        
        # Sysadmin check - block immediately
        is_sysadmin = int(user.get("is_sysadmin", 0))
        if is_sysadmin:
            result["error"] = "Sysadmin keys are not allowed for MCP registration. Please use a regular user key or a team admin key."
            return result
        
        result["valid"] = True
        result["user"] = {
            "userid": user.get("userid"),
            "fullname": user.get("fullname") or f"{user.get('firstname', '')} {user.get('lastname', '')}".strip(),
            "is_sysadmin": 0,
            "team": user.get("team"),
        }
        is_sysadmin = int(user.get("is_sysadmin", 0))
        current_team = user.get("team")

        # Check per-key can_write from /apikeys
        key_id = api_key.split("-")[0]
        key_can_write = 0
        try:
            keys_resp = await client.get(f"{url}/apikeys", headers=headers)
            if keys_resp.status_code == 200:
                for k in keys_resp.json():
                    if str(k.get("id")) == key_id:
                        key_can_write = int(k.get("can_write", 0))
                        break
        except Exception:
            pass

        can_write = bool(is_sysadmin) or bool(key_can_write)
        if current_team and can_write:
            team_resp = await client.get(f"{url}/teams/{current_team}", headers=headers)
            if team_resp.status_code == 200:
                team_data = team_resp.json()
                can_write = bool(
                    int(team_data.get("users_canwrite_experiments", 0))
                    or int(team_data.get("users_canwrite_resources", 0))
                )
        result["can_write"] = can_write
    except httpx.TimeoutError:
        result["error"] = f"Connection timeout for {base_url}."
    except httpx.ConnectError as e:
        result["error"] = f"Connection error: {e}"
    except Exception as e:
        result["error"] = f"Validation error: {e}"
    return result



# ── HTML templates ──


PROFILE_NAMES = {"r": "Read-only", "h": "Hybrid", "f": "Full"}
REGFORM_CSS = """<style>
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #0b0f1a; --bg2: #131827; --bg3: #1a2236;
  --brd: #1f2b40; --brd-hover: #2a3f60;
  --fg: #e8edf5; --muted: #8898b4; --neutral: #5c6f8c;
  --acc: #3b82f6; --acc-hover: #2563eb;
  --acc-glow: rgba(59,130,246,0.15);
  --rad: 14px; --rad-sm: 10px;
  --shadow: 0 8px 32px rgba(0,0,0,0.4);
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif;
  background: var(--bg); color: var(--fg);
  min-height: 100vh; display: flex; justify-content: center; align-items: center;
  padding: 20px; line-height: 1.5;
}
.card {
  background: var(--bg2); border: 1px solid var(--brd);
  border-radius: var(--rad); padding: 36px; max-width: 480px; width: 100%;
  box-shadow: var(--shadow);
  animation: fadeUp 0.35s var(--ease) both;
}
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
h2 { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 4px; color: var(--fg); }
.sub { font-size: 0.82rem; color: var(--muted); margin-bottom: 24px; line-height: 1.5; }
.field-label { display: block; font-size: 0.72rem; font-weight: 600; color: var(--neutral); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
input[type=text], input[type=password] {
  width: 100%; padding: 11px 14px; margin-bottom: 18px;
  background: var(--bg3); border: 1px solid var(--brd);
  border-radius: var(--rad-sm); color: var(--fg); font-size: 0.9rem;
  outline: none; transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease);
  box-sizing: border-box; font-family: inherit;
}
input:focus { border-color: var(--acc); box-shadow: 0 0 0 3px var(--acc-glow); }
input::placeholder { color: var(--neutral); }
button {
  width: 100%; padding: 12px; margin-top: 4px;
  background: var(--acc); color: #fff; border: none;
  border-radius: var(--rad-sm); font-size: 0.88rem; font-weight: 600;
  cursor: pointer; transition: background 0.2s var(--ease), transform 0.15s var(--ease);
  font-family: inherit; letter-spacing: 0.01em;
}
button:hover { background: var(--acc-hover); transform: translateY(-1px); }
button:active { transform: translateY(0); }
.alert { padding: 12px 16px; border-radius: var(--rad-sm); font-size: 0.82rem; margin-bottom: 18px; animation: fadeUp 0.25s var(--ease) both; }
.alert-error { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); color: #fca5a5; }

/* Profile cards */
.profile-cards { display: flex; flex-direction: column; gap: 10px; margin: 16px 0 20px; }
.profile-card {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 14px 16px; background: var(--bg3); border: 1.5px solid var(--brd);
  border-radius: var(--rad-sm); cursor: pointer;
  transition: border-color 0.2s var(--ease), background 0.2s var(--ease);
  position: relative;
}
.profile-card:hover { border-color: var(--brd-hover); background: rgba(26,34,54,0.7); }
.profile-card input[type=radio] { position: absolute; opacity: 0; width: 0; height: 0; }
.profile-card .radio-dot {
  flex-shrink: 0; width: 20px; height: 20px;
  border: 2px solid var(--brd-hover); border-radius: 50%;
  margin-top: 1px; position: relative;
  transition: border-color 0.2s var(--ease);
}
.profile-card .radio-dot::after {
  content: ""; position: absolute; inset: 3px;
  border-radius: 50%; background: var(--acc);
  transform: scale(0); transition: transform 0.2s var(--ease);
}
.profile-card input[type=radio]:checked + .radio-dot { border-color: var(--acc); box-shadow: 0 0 0 3px var(--acc-glow); }
.profile-card input[type=radio]:checked + .radio-dot::after { transform: scale(1); }
.profile-card:has(input[type=radio]:checked) { border-color: var(--acc); background: rgba(59,130,246,0.06); }
.pcard-title { font-size: 0.9rem; font-weight: 600; color: var(--muted); margin-bottom: 2px; transition: color 0.2s var(--ease); display: block; }
.profile-card:has(input[type=radio]:checked) .pcard-title { color: var(--fg); }
.pcard-desc { font-size: 0.78rem; color: var(--neutral); line-height: 1.4; }

/* Info boxes */
.info-box { padding: 14px 16px; border-radius: var(--rad-sm); margin-bottom: 16px; font-size: 0.82rem; animation: fadeUp 0.25s var(--ease) both; }
.info-box.write { background: rgba(59,130,246,0.06); border: 1px solid rgba(59,130,246,0.15); }
.info-box.none { background: rgba(234,179,8,0.06); border: 1px solid rgba(234,179,8,0.15); }
.info-box p { margin: 0; }
.info-box strong { color: var(--fg); }
.info-muted { color: var(--muted); margin-top: 2px; }

/* URL box */
.url-box { background: var(--bg3); padding: 14px; border-radius: var(--rad-sm); word-break: break-all; font-family: "SF Mono", "Fira Code", monospace; font-size: 0.72rem; border: 1px solid var(--brd); margin: 16px 0; color: var(--acc); line-height: 1.5; }
.footer { font-size: 0.75rem; color: var(--neutral); margin-top: 20px; }
a { color: var(--acc); text-decoration: none; transition: color 0.15s var(--ease); }
a:hover { color: #60a5fa; }
</style>"""

def _create_register_form(error: str = "") -> str:
    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>elabFTW MCP Registration</title>
{REGFORM_CSS}</head><body>
<div class="card">
<h2>elabFTW MCP Registration</h2>
<p class="sub">Enter your elabFTW credentials to generate a permanent MCP session URL.</p>
{err_html}
<form method="post">
<label class="field-label">elabFTW Base URL</label>
<input type="text" name="base_url" value="https://elntest.ub.tum.de" required>
<label class="field-label">elabFTW API Key</label>
<input type="password" name="api_key" placeholder="Paste your elabFTW API key" required>

<script>
function toggleAllTools(checkbox) {{{{
  var tools = document.querySelectorAll('input[name="tools"]:not([value="all"])');
  tools.forEach(function(t) {{{{ t.checked = checkbox.checked; }}}});
}}}}
</script>
<button type="submit">Generate MCP URL</button>
</form>
</div>

</body></html>"""


# KEPT FOR BACKWARD COMPAT - _success_page is the new version


# ── Routes ──


def _profile_form(base_url, api_key, user_info, can_write, error=""):
    err_html = f'<div class="alert alert-error">{error}</div>' if error else ""
    fullname = (user_info or {}).get("fullname", "Unknown") or "Unknown"
    key_type = "write" if can_write else "read-only"
    key_bg = "rgba(59,130,246,0.1)" if can_write else "rgba(234,179,8,0.1)"
    key_bd = "rgba(59,130,246,0.2)" if can_write else "rgba(234,179,8,0.2)"
    key_cl = "var(--acc)" if can_write else "#e5a500"
    key_type_badge = f'<span style="display:inline-block;padding:2px 8px;background:{key_bg};border:1px solid {key_bd};border-radius:4px;font-size:0.72rem;font-weight:600;color:{key_cl};margin-left:8px">{key_type}</span>'
    
    if can_write:
        radios = ""
        for k, n, d in [("r","Read-only","Browse & search only"),("h","Hybrid","Read + AI suggestions, tags"),("f","Full","All tools enabled")]:
            chk = ' checked' if k == 'h' else ''
            radios += '<label class="preset-card"><input type="radio" name="profile" value="' + k + '" data-preset="' + k + '" ' + chk + '><span class="preset-radio"></span><span class="preset-card-text"><span class="preset-name">' + n + '</span><span class="preset-badge">' + d + '</span></span></label>'
        info_box = '<div style="margin-bottom:20px"><p style="font-size:0.82rem;color:var(--muted);margin-bottom:10px"><strong>' + fullname + '</strong>' + key_type_badge + ' &mdash; API key has write access</p><h3 style="font-size:0.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:8px">Profile Preset</h3><div class="preset-grid">' + radios + '</div></div>'
        btn = "Generate MCP URL"
    else:
        info_box = '<div style="margin-bottom:20px"><p style="font-size:0.82rem;color:var(--muted);margin-bottom:10px"><strong>' + fullname + '</strong>' + key_type_badge + ' &mdash; read-only key</p></div>'
        btn = "Generate MCP URL"
    
    read_tools = [
        ("get_connection_info","Connection details","Server URL, active user identity, team, available categories and statuses"),
        ("get_current_user_capabilities","User capabilities","Current user permissions, team membership, admin/sysadmin flags"),
        ("refresh_team_caps","Refresh team caps","Refresh cached team capability flags for current session"),
        ("list_item_statuses","Item statuses","All available statuses for database items"),
        ("list_experiment_statuses","Experiment statuses","All available statuses for experiments"),
        ("get_experiment","Get experiment","Full experiment: body, metadata, tags, comments, links, uploads"),
        ("list_experiments","List experiments","Search or list experiments with category/status/owner/tag filters"),
        ("get_item","Get item","Full database item with all metadata fields"),
        ("list_items","List items","Search or list database items with category/status/owner/tag filters"),
        ("list_experiment_categories","Experiment categories","All experiment categories with id, title, color, default flag"),
        ("list_item_categories","Item categories","All item/resource categories with id, title, color"),
        ("list_experiment_templates","Experiment templates","All reusable experiment templates with paging support"),
        ("get_experiment_template","Get template","Single template with full body, metadata, and steps"),
        ("list_item_types","Item types","All item types (resource categories) with default body templates"),
        ("get_item_type","Get item type","Single item type with full body, metadata, and steps"),
        ("list_steps","List steps","All steps/tasks with completion status (0/1) and ordering"),
        ("get_entity_links","Entity links","All outgoing and incoming links for an entity with target metadata"),
        ("expand_links_network","Link network","BFS link graph traversal from root entity up to configurable depth"),
        ("resolve_entity_by_query","Resolve by query","Find experiment/item by search query, returns candidate list"),
    ]
    write_tools = [
        ("add_step","Add step","Append a new step/task to an experiment, item, or template"),
        ("update_step","Update step","Modify the text body of an existing step"),
        ("toggle_step","Toggle step","Mark a step as complete or incomplete"),
        ("delete_step","Delete step","Permanently remove a step from an entity"),
        ("create_experiment","Create experiment","Create new experiment with title, body, category, status, tags"),
        ("create_item","Create item","Create new database item (resource) with title, body, category"),
        ("create_experiment_from_template","Create from template","Create experiment using an existing template, copying steps"),
        ("update_experiment_body","Update experiment","Append or overwrite experiment body (preserves content type)"),
        ("update_item_body","Update item","Append or overwrite item body (preserves content type)"),
        ("update_entity_metadata","Update metadata","Update extra_fields metadata with merge or overwrite mode"),
        ("update_entity_fields","Update fields","Update top-level fields: title, status, category on entity"),
        ("ensure_link","Create link","Idempotently create directed link between two entities"),
        ("bulk_ensure_links","Bulk create links","Create multiple directed links in one call"),
        ("delete_link","Delete link","Idempotently remove a directed link between two entities"),
        ("bulk_delete_links","Bulk delete links","Remove multiple directed links in one call"),
        ("ensure_link_by_query","Link by query","Resolve target entity by search query and create the link"),
    ]
    ai_tools = [
        ("review_experiment","AI review","AI-generated structured review summary for an experiment"),
        ("suggest_tags","Suggest tags","AI-suggested tags based on experiment/item content analysis"),
        ("suggest_metadata","Suggest metadata","AI-suggested structured metadata key-value pairs"),
        ("apply_tag_suggestions","Apply tags","Persist AI-suggested tags to experiment or item"),
        ("add_ai_review_comment","AI comment","Attach AI-generated review comment with provenance header"),
    ]
    
    tools_html = '<div style="margin:20px 0"><h3 style="font-size:0.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px">Tools</h3>'
    categories = [("read","Read",read_tools)]
    if can_write:
        categories += [("write","Write",write_tools), ("ai","AI",ai_tools)]
    for cat_id, cat_name, cat_tools in categories:
        tools_html += '<div class="tool-section"><div class="tool-section-header" onclick="toggleSection(\'' + cat_id + '\')"><label style="display:flex;align-items:center;gap:6px;font-size:0.78rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;cursor:pointer"><div class="toggle-switch" style="width:44px;height:24px"><input type="checkbox" id="' + cat_id + '_toggle" checked onchange="event.stopPropagation();toggleCategoryCheckbox(\'' + cat_id + '\',this)" style="position:absolute;opacity:0;width:0;height:0"><span class="toggle-slider"></span></div>' + cat_name + ' <span style="color:var(--neutral);font-weight:400">(' + str(len(cat_tools)) + ')</span></label><span class="cat-arrow" id="' + cat_id + '_arrow">&#9654;</span></div><div id="' + cat_id + '">'
        for t_name, t_label, t_desc in cat_tools:
            tools_html += '<div class="tool-row" onclick="if(!event.target.closest(''.toggle-switch''))this.classList.toggle(''expanded'')"><div class="toggle-wrapper"><label class="toggle-label"><span class="toggle-text">' + t_label + '</span><div class="toggle-switch"><input type="checkbox" name="tools" value="' + t_name + '" class="' + cat_id + '_item" checked><span class="toggle-slider"></span></div></label></div></div>'
        tools_html += '</div></div>'
    tools_html += '</div>'
    
    js = "<script>function toggleSection(id){var el=document.getElementById(id);var arr=document.getElementById(id+'_arrow');if(el.style.display==='none'){el.style.display='block';arr.classList.remove('open')}else{el.style.display='none';arr.classList.add('open')}}function toggleCategoryCheckbox(cid,cb){var items=document.querySelectorAll('.'+cid+'_item');items.forEach(function(t){t.checked=cb.checked});updateAllToggle()}function updateAllToggle(){['read','write','ai'].forEach(function(id){var ct=document.getElementById(id+'_toggle');if(ct){var its=document.querySelectorAll('.'+id+'_item');ct.checked=Array.from(its).every(function(t){return t.checked})}})}function applyPreset(p){var r=document.querySelectorAll('.read_item'),w=document.querySelectorAll('.write_item'),ai=document.querySelectorAll('.ai_item');if(p==='r'){r.forEach(function(t){t.checked=true});w.forEach(function(t){t.checked=false});ai.forEach(function(t){t.checked=false})}else if(p==='h'){r.forEach(function(t){t.checked=true});w.forEach(function(t){t.checked=false});ai.forEach(function(t){t.checked=true})}else if(p==='f'){r.forEach(function(t){t.checked=true});w.forEach(function(t){t.checked=true});ai.forEach(function(t){t.checked=true})}updateAllToggle()}document.querySelectorAll('input[name=profile][data-preset]').forEach(function(r){r.addEventListener('change',function(){applyPreset(this.value)})});document.querySelectorAll('.toggle-switch input').forEach(function(cb){cb.addEventListener('change',function(){var cl=Array.from(this.classList).find(function(c){return c.endsWith('_item')});if(cl){var id=cl.replace('_item','');var ct=document.getElementById(id+'_toggle');var its=document.querySelectorAll('.'+cl);ct.checked=Array.from(its).every(function(t){return t.checked})}})});document.addEventListener('DOMContentLoaded',function(){applyPreset('h')});</script>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>elabFTW MCP Registration</title>
{REGFORM_CSS}
</head><body>
<div class="card">
<h2>elabFTW MCP Registration</h2>
{err_html}
<form method="post">
<label class="field-label">elabFTW Base URL</label>
<input type="text" name="base_url" value="{base_url}">
<label class="field-label">elabFTW API Key</label>
<input type="password" name="api_key" value="{api_key}">
<input type="hidden" name="validated" value="1">
{info_box}
{tools_html}
<button type="submit">{btn}</button>
</form>
</div>
{js}
</body></html>"""

def _success_page(personal_url, profile, prefix="/el"):
    pname = PROFILE_NAMES.get(profile, "Read-only")
    buttons = """<div style="display:flex;gap:10px;margin-top:18px;flex-direction:column">
  <div style="display:flex;gap:10px">
    <button onclick="(function(e){var b=document.querySelector('.url-box');if(!b||!b.textContent)return;var u=b.textContent.trim();var t=u.split('token=')[1];if(!t)return;t=t.split(/[\s<&]/)[0];navigator.clipboard.writeText(t).then(function(){var btn=e.currentTarget||e;btn.innerHTML='<span style=font-size:1em>\u2713</span> Copied';btn.style.borderColor='#22c55e';setTimeout(function(){btn.innerHTML='\U0001f4cb Copy Token';btn.style.borderColor=''},2500)}).catch(function(){prompt('Token:',t)})})(this)" type="button" title="Copy only the JWT token (without URL)" style="flex:1;padding:11px 16px;background:var(--bg3);color:var(--fg);border:1.5px solid var(--brd-hover);border-radius:var(--rad-sm);font-size:0.82rem;font-weight:600;cursor:copy;font-family:inherit;display:flex;align-items:center;gap:8px;justify-content:center;transition:all 0.15s ease;min-height:44px" onmousedown="this.style.transform='scale(0.97)'" onmouseup="this.style.transform=''" onmouseleave="this.style.transform=''">\U0001f4cb Copy Token</button>
    <button onclick="(function(e){var b=document.querySelector('.url-box');if(!b||!b.textContent)return;var u=b.textContent.trim();navigator.clipboard.writeText(u).then(function(){var btn=e.currentTarget||e;btn.innerHTML='<span style=font-size:1em>\u2713</span> Copied';btn.style.background='#22c55e';setTimeout(function(){btn.innerHTML='\U0001f4c2 Copy URL';btn.style.background=''},2500)}).catch(function(){prompt('URL:',u)})})(this)" type="button" title="Copy the full MCP URL with token" style="flex:1;padding:11px 16px;background:var(--acc);color:#fff;border:none;border-radius:var(--rad-sm);font-size:0.82rem;font-weight:600;cursor:copy;font-family:inherit;display:flex;align-items:center;gap:8px;justify-content:center;transition:all 0.15s ease;min-height:44px" onmousedown="this.style.transform='scale(0.97)'" onmouseup="this.style.transform=''" onmouseleave="this.style.transform=''">\U0001f4c2 Copy URL</button>
  </div>
  <p style="font-size:0.7rem;color:var(--neutral);margin:4px 0 0;text-align:center">Click to copy &mdash; token only or full URL</p>
</div>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Registration Successful</title>
{REGFORM_CSS}</head><body>
<div class="card">
<h2>Registration Successful</h2>
<p>Profile: <strong>{pname}</strong></p>
<p>Use the following URL in your MCP client:</p>
<div class="url-box">
{personal_url}
</div>
<p class="footer">Token expires in 30 days. To change profile, re-register.</p>
{buttons}
<a href="{prefix}/register">&larr; Register another key</a>
</div>
<script>
function toggleAllTools(cb) {{
  document.querySelectorAll('input[name="tools"]').forEach(function(t) {{
    if (t.value !== 'all') t.checked = cb.checked;
  }});
}}
function applyPreset(preset) {{
  var readTools = document.querySelectorAll('input[name="tools"][data-cat="read"]');
  var writeTools = document.querySelectorAll('input[name="tools"][data-cat="write"]');
  var aiTools = document.querySelectorAll('input[name="tools"][data-cat="ai"]');
  var allCb = document.querySelector('input[name="tools"][value="all"]');
  
  if (preset === 'r') {{
    readTools.forEach(function(t) {{ t.checked = true; }});
    writeTools.forEach(function(t) {{ t.checked = false; }});
    aiTools.forEach(function(t) {{ t.checked = false; }});
  }} else if (preset === 'h') {{
    readTools.forEach(function(t) {{ t.checked = true; }});
    writeTools.forEach(function(t) {{ t.checked = false; }});
    aiTools.forEach(function(t) {{ t.checked = true; }});
  }} else if (preset === 'f') {{
    readTools.forEach(function(t) {{ t.checked = true; }});
    writeTools.forEach(function(t) {{ t.checked = true; }});
    aiTools.forEach(function(t) {{ t.checked = true; }});
  }}
  // Update "All" checkbox
  var allTools = document.querySelectorAll('input[name="tools"]:not([value="all"])');
  var allChecked = Array.from(allTools).every(function(t) {{ return t.checked; }});
  if (allCb) allCb.checked = allChecked;
}}
// Listen for profile radio changes
document.querySelectorAll('input[name="profile"][data-preset]').forEach(function(radio) {{
  radio.addEventListener('change', function() {{
    applyPreset(this.value);
  }});
}});
// Initialize with hybrid preset
document.addEventListener('DOMContentLoaded', function() {{
  applyPreset('h');
}});
</script>
</body></html>"""


async def register_page(request: Request):
    if request.method == "POST":
        form = await request.form()
        api_key = str(form.get("api_key", "")).strip()
        base_url = str(form.get("base_url", "")).strip()
        validated = str(form.get("validated", "0")).strip()
        profile = str(form.get("profile", "")).strip()

        if not api_key or not base_url:
            return HTMLResponse(_create_register_form("Both fields required."), status_code=400)

        # ALWAYS validate the key first
        validation = await _validate_elabftw_key(base_url, api_key)
        if not validation["valid"]:
            return HTMLResponse(
                _create_register_form(validation.get("error", "Key rejected by elabFTW API.")),
                status_code=401,
            )

        # Key is valid — proceed based on step
        if validated == "1" and profile in ("r", "h", "f"):
            # Step 2: User already saw profile selection, generate token
            try:
                # Get selected tools from form
                selected_tools = form.getlist("tools")
                enabled_tools = selected_tools if selected_tools and "all" not in selected_tools else None
                token = encode_token(base_url, api_key, profile=profile, enabled_tools=enabled_tools)
            except RuntimeError as e:
                logger.error("Token creation failed: %s", e)
                return HTMLResponse(_create_register_form("Server misconfiguration."), status_code=500)
            fwd = request.headers.get("x-forwarded-proto", "https")
            host = request.headers.get("host", "localhost:8081")
            prefix = os.environ.get("URL_PREFIX", "/el").strip().strip("/")
            personal_url = f"{fwd}://{host}/{prefix}/mcp?token={token}"
            remote_ip = request.client.host if request.client else "unknown"
            logger.info("Registered JWT from %s (profile=%s)", remote_ip, profile)
            _audit("REGISTER", remote_ip=remote_ip, profile=profile)
            return HTMLResponse(_success_page(personal_url, profile, prefix="/" + prefix))

        # Step 1: Show profile selection
        return HTMLResponse(
            _profile_form(base_url, api_key, validation["user"], validation["can_write"])
        )

    return HTMLResponse(_create_register_form())
async def handle_mcp(request: Request):
    """Handle both GET and POST to /mcp.

    GET  → ensure R worker is running, return 204 (no SSE streaming).
    POST → decode JWT, proxy to shared R worker with auth headers.
    """
    if request.method == "GET":
        # Ensure the shared R worker is running
        if not r_worker.is_alive:
            try:
                await r_worker.start()
            except RuntimeError as e:
                return HTMLResponse(str(e), status_code=503)
        return Response(status_code=204)

    # POST: decode JWT and proxy to R
    token = request.query_params.get("token", "")
    result = _get_creds_and_profile_from_jwt(token)
    if result is None:
        _audit("POST_INVALID_TOKEN", token_prefix=token[:16] if token else "none")
        return HTMLResponse("Invalid or expired token.", status_code=401)

    api_key, base_url, profile, enabled_tools = result

    if not r_worker.is_alive:
        try:
            await r_worker.start()
        except RuntimeError as e:
            return HTMLResponse(str(e), status_code=503)

    body = await request.body()
    
    # Check if this is a tools/call request and if the tool is enabled
    if enabled_tools:
        try:
            import json
            body_json = json.loads(body)
            method = body_json.get("method", "")
            if method == "tools/call":
                tool_name = body_json.get("params", {}).get("name", "")
                if tool_name and tool_name not in enabled_tools:
                    return Response(
                        content=json.dumps({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Tool '{tool_name}' is not enabled for this token"}}),
                        media_type="application/json",
                        status_code=403
                    )
        except:
            pass
    
    status, resp_text = await r_worker.proxy_request(api_key, base_url, body, extra_headers={"X-Write-Scope": profile})

    if status == 202:
        # Notification accepted — no response body
        return Response(status_code=202)

    if status == 200 and resp_text:
        # Filter tools/list response if enabled_tools is set
        if enabled_tools:
            try:
                import json
                resp_json = json.loads(resp_text)
                if "result" in resp_json and "tools" in resp_json["result"]:
                    original_count = len(resp_json["result"]["tools"])
                    resp_json["result"]["tools"] = [t for t in resp_json["result"]["tools"] if t.get("name") in enabled_tools]
                    filtered_count = len(resp_json["result"]["tools"])
                    if filtered_count < original_count:
                        resp_text = json.dumps(resp_json)
            except:
                pass
        return Response(
            content=resp_text,
            media_type="application/json",
        )

    if status == 200 and not resp_text:
        return HTMLResponse("Empty response from R worker", status_code=502)

    return HTMLResponse(resp_text or f"R worker error (HTTP {status})", status_code=status)


async def status_endpoint(request: Request):
    return HTMLResponse(
        json.dumps({
            "r_worker_alive": r_worker.is_alive,
            "r_worker_ready": r_worker.is_ready,
        }),
        media_type="application/json",
    )


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the shared R worker at boot
    try:
        await r_worker.start()
    except RuntimeError as e:
        logger.error("Failed to start shared R worker: %s", e)
    yield
    await r_worker.shutdown()


# ── App factory ──

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.api_route("/register", methods=["GET", "POST"])
    @limiter.limit(os.environ.get("ELABMCP_RATE_LIMIT", "10/minute"))
    async def register_route(request: Request):
        return await register_page(request)

    @app.api_route("/mcp", methods=["GET", "POST"])
    async def mcp_route(request: Request):
        return await handle_mcp(request)

    @app.get("/status")
    async def status_route(request: Request):
        return await status_endpoint(request)

    return app
