# Everse-Karte in das (bereits TGA-gepatchte) Bundle einfuegen.
# Liest GUI_JS, schreibt GUI_JS_OUT. Keine Backslash-Escapes, Emoji als chr().
import os
P = os.environ["GUI_JS"]
OUT = os.environ["GUI_JS_OUT"]
data = open(P, "rb").read()
marker = b'Object(ve.jsxs)(sc,{xs:6,title:"Interactive Search"'
assert data.count(marker) == 1, "Marker count: %d" % data.count(marker)
EMOJI = chr(0x1F4AC)
card_parts = [
    'Object(ve.jsx)(Xs.a,{item:!0,xs:12,children:Object(ve.jsx)("a",{',
    'href:"https://researchmcp.duckdns.org/nomad-oasis/api/everse/",',
    'style:{display:"flex",alignItems:"center",justifyContent:"space-between",gap:16,',
    'flexWrap:"wrap",background:"linear-gradient(135deg,#0d9488,#115e59)",color:"#fff",',
    'borderRadius:12,padding:"16px 20px",margin:"2px 0 10px",',
    'boxShadow:"0 6px 18px rgba(17,94,89,.30)",textDecoration:"none"},',
    'children:[Object(ve.jsxs)("span",{style:{display:"flex",alignItems:"center",gap:16},',
    'children:[Object(ve.jsx)("span",{style:{fontSize:28,lineHeight:1},',
    'children:"' + EMOJI + '"}),',
    'Object(ve.jsxs)("span",{children:[',
    'Object(ve.jsx)("span",{style:{display:"block",fontWeight:600,fontSize:"1.16rem",',
    'letterSpacing:"-.01em"},children:"Everse Chatbot"}),',
    'Object(ve.jsx)("span",{style:{display:"block",opacity:.92,fontSize:".92rem",marginTop:2},',
    'children:"Ask the e-conversion knowledge base: models, papers, methods. '
    'Opens logged in with your NOMAD account."})]})]}),',
    'Object(ve.jsx)("span",{style:{flexShrink:0,background:"#fff",color:"#0f766e",',
    'fontWeight:600,padding:"10px 20px",borderRadius:8,fontSize:".95rem"},',
    'children:"Open the chat"})]})}),',
]
card = "".join(card_parts).encode("utf-8")
assert b"Everse Chatbot" not in data, "Everse-Karte schon vorhanden"
open(OUT, "wb").write(data.replace(marker, card + marker))
print("patched:", len(data) + len(card), "orig:", len(data), "card:", len(card))
