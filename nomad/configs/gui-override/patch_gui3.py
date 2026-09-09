# Patch the NOMAD GUI bundle: insert a TGA card above the "Interactive Search" InfoCard.
# NO backslash escapes anywhere (write_file/patch double-escape them): no \n, no \uXXXX.
# Newlines are unnecessary in minified JS; the thermometer emoji is embedded as real UTF-8.
import os

P = os.environ.get('GUI_JS', "/opt/venv/lib/python3.12/site-packages/nomad/app/static/gui/static/js/main.d7847511.chunk.js")
OUT = os.environ.get('GUI_JS_OUT', "/tmp/gui-main.patched.js")

data = open(P, "rb").read()

marker = b'Object(ve.jsxs)(sc,{xs:6,title:"Interactive Search"'
assert data.count(marker) == 1, "Marker count: %d" % data.count(marker)

EMOJI = chr(0x1F321) + chr(0xFE0F)

card_parts = [
    'Object(ve.jsx)(Xs.a,{item:!0,xs:12,children:Object(ve.jsx)("a",{',
    'href:"https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/",',
    'style:{display:"flex",alignItems:"center",justifyContent:"space-between",gap:16,',
    'flexWrap:"wrap",background:"linear-gradient(135deg,#5e6ad2,#4338ca)",color:"#fff",',
    'borderRadius:12,padding:"16px 20px",margin:"2px 0 10px",',
    'boxShadow:"0 6px 18px rgba(67,56,202,.30)",textDecoration:"none"},',
    'children:[Object(ve.jsxs)("span",{style:{display:"flex",alignItems:"center",gap:16},',
    'children:[Object(ve.jsx)("span",{style:{fontSize:28,lineHeight:1},',
    'children:"' + EMOJI + '"}),',
    'Object(ve.jsxs)("span",{children:[',
    'Object(ve.jsx)("span",{style:{display:"block",fontWeight:600,fontSize:"1.16rem",',
    'letterSpacing:"-.01em"},children:"TGA Measurement Requests"}),',
    'Object(ve.jsx)("span",{style:{display:"block",opacity:.92,fontSize:".92rem",marginTop:2},',
    'children:"Order a thermogravimetric run: sample, atmosphere, unlimited temperature segments. '
    'One click creates the request for the operator."})]})]}),',
    'Object(ve.jsx)("span",{style:{flexShrink:0,background:"#fff",color:"#4338ca",',
    'fontWeight:600,padding:"10px 20px",borderRadius:8,fontSize:".95rem"},',
    'children:"Open the form"})]})}),',
]
card = "".join(card_parts).encode("utf-8")

new = data.replace(marker, card + marker)
open(OUT, "wb").write(new)
print("patched:", len(new), "orig:", len(data), "card:", len(card))
