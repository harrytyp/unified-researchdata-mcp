"""Registration page: a NOMAD API key in, a personal MCP URL out."""

import html

from .server import tool_descriptions

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:#0b0f1a;color:#e8edf5;min-height:100vh;display:flex;align-items:center;
justify-content:center;padding:24px}
.card{background:#131827;border:1px solid #1f2b40;border-radius:14px;padding:2rem;
max-width:620px;width:100%}
h1{font-size:1.15rem;font-weight:700;margin-bottom:.35rem}
h2{font-size:.8rem;font-weight:600;color:#8898b4;text-transform:uppercase;
letter-spacing:.06em;margin:1.4rem 0 .6rem}
p{font-size:.85rem;color:#8898b4;margin-bottom:1.1rem;line-height:1.55}
label{display:block;font-size:.82rem;font-weight:600;margin-bottom:.3rem;color:#8898b4}
input[type=text],input[type=password]{width:100%;padding:.6rem .75rem;background:#1a2236;
border:1px solid #1f2b40;border-radius:8px;color:#e8edf5;font-size:.9rem;outline:none;
margin-bottom:.9rem}
input:focus{border-color:#3b82f6}
button{width:100%;padding:.65rem;background:#3b82f6;color:#fff;border:none;
border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer}
button:hover{opacity:.92}
.error{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#fca5a5;
border-radius:8px;padding:.75rem .9rem;font-size:.82rem;margin-bottom:1rem}
.tools{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px}
.tool{display:flex;align-items:flex-start;gap:8px;padding:8px 10px;background:#1a2236;
border:1px solid #1f2b40;border-radius:8px;cursor:pointer}
.tool span.name{font-size:.76rem;color:#e8edf5;display:block}
.tool span.desc{font-size:.68rem;color:#5c6f8c;display:block;margin-top:2px;line-height:1.35}
.box{background:#1a2236;border:1px solid #1f2b40;border-radius:8px;padding:.85rem;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.75rem;
word-break:break-all;margin:.85rem 0;color:#e8edf5}
.note{font-size:.75rem;color:#5c6f8c}
a{color:#3b82f6;text-decoration:none;font-size:.82rem}
a:hover{text-decoration:underline}
.ok{display:inline-block;padding:2px 9px;background:rgba(34,197,94,.12);
border:1px solid rgba(34,197,94,.3);border-radius:6px;font-size:.72rem;font-weight:700;
color:#22c55e;text-transform:uppercase;letter-spacing:.03em}
.ro{display:inline-block;padding:2px 9px;background:rgba(59,130,246,.12);
border:1px solid rgba(59,130,246,.3);border-radius:6px;font-size:.72rem;font-weight:700;
color:#3b82f6;text-transform:uppercase;letter-spacing:.03em}
"""


def _page(body: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>NOMAD MCP — Registration</title><style>{CSS}</style></head>"
        f"<body><div class=\"card\">{body}</div></body></html>"
    )


def register_page(base_url: str, error: str = "") -> str:
    """The form: key in, tools chosen, URL out."""
    alert = f'<div class="error">{html.escape(error)}</div>' if error else ""
    rows = []
    for name, description in tool_descriptions():
        rows.append(
            '<label class="tool">'
            f'<input type="checkbox" name="tools" value="{html.escape(name)}" checked>'
            f'<span><span class="name">{html.escape(name)}</span>'
            f'<span class="desc">{html.escape(description)}</span></span></label>'
        )
    return _page(
        "<h1>NOMAD MCP</h1>"
        '<p>Enter a NOMAD personal access token to get a personal MCP URL. '
        'The token stays in your URL — nothing is stored on the server.</p>'
        f"{alert}"
        '<form method="post">'
        '<label for="base_url">NOMAD API base URL</label>'
        f'<input id="base_url" type="text" name="base_url" value="{html.escape(base_url)}">'
        '<label for="api_key">NOMAD API key</label>'
        '<input id="api_key" type="password" name="api_key" '
        'placeholder="Paste your NOMAD personal access token" required>'
        '<h2>Tools <span class="ro">read-only</span></h2>'
        f'<div class="tools">{"".join(rows)}</div>'
        '<div style="height:1.2rem"></div>'
        '<button type="submit">Create MCP URL</button>'
        "</form>"
        '<p class="note" style="margin-top:1rem">NOMAD tokens are created in the GUI '
        "under <em>Account → Personal access tokens</em>. This server never writes to "
        "NOMAD, so a read-only token is enough.</p>"
    )


def register_result(url: str, token: str, name: str, tools: int) -> str:
    """What the user takes away."""
    who = f" for <strong>{html.escape(name)}</strong>" if name else ""
    return _page(
        '<h1>Ready<span class="ok" style="margin-left:.5rem">validated</span></h1>'
        f"<p>Key accepted{who}. {tools} read-only tools are enabled on this URL.</p>"
        f'<div class="box" id="url">{html.escape(url)}</div>'
        '<p class="note">Paste the whole URL into your MCP client, or just the part '
        "after <code>token=</code> where a client asks for a token separately. "
        "It is valid for 30 days.</p>"
        '<p style="margin-top:1rem"><a href="register">← register another key</a></p>'
    )
