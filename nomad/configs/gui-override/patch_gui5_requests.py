# Patch the NOMAD GUI bundle: a second TGA card for "My requests & ELN",
# inserted right after the existing TGA request card.
# NO backslash escapes anywhere (write_file/patch double-escape them): no \n, no \uXXXX.
# Newlines are unnecessary in minified JS; the emoji is embedded as real UTF-8.
#
# Reads the already patched bundle (TGA card + Everse card) and writes it back
# in place, like patch_gui4_everse.py. Anchor is the end of the request card:
# the CTA text "Open the form" is unique on the page.
import os
import sys

P = os.environ.get("GUI_JS", "main.d7847511.chunk.js")
OUT = os.environ.get("GUI_JS_OUT", P)

data = open(P, "rb").read()

anchor = b'children:"Open the form"})]})}),'
count = data.count(anchor)
if count != 1:
    sys.exit("Anker %d mal gefunden - Abbruch (Home-Komponente geaendert?)" % count)

EMOJI = chr(0x1F4C1)  # file folder

card_parts = [
    'Object(ve.jsx)(Xs.a,{item:!0,xs:12,children:Object(ve.jsx)("a",{',
    'href:"https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/requests",',
    'style:{display:"flex",alignItems:"center",justifyContent:"space-between",gap:16,',
    'flexWrap:"wrap",background:"#eef2ff",color:"#312e81",border:"1px solid #c7d2fe",',
    'borderRadius:12,padding:"14px 20px",margin:"2px 0 10px",',
    'boxShadow:"0 2px 8px rgba(67,56,202,.12)",textDecoration:"none"},',
    'children:[Object(ve.jsxs)("span",{style:{display:"flex",alignItems:"center",gap:16},',
    'children:[Object(ve.jsx)("span",{style:{fontSize:26,lineHeight:1},',
    'children:"' + EMOJI + '"}),',
    'Object(ve.jsxs)("span",{children:[',
    'Object(ve.jsx)("span",{style:{display:"block",fontWeight:600,fontSize:"1.08rem",',
    'letterSpacing:"-.01em"},children:"My TGA Requests and ELN"}),',
    'Object(ve.jsx)("span",{style:{display:"block",opacity:.85,fontSize:".9rem",marginTop:2},',
    'children:"Follow your requests, see when results are ready, take them into your '
    'eLabFTW or download the data package."})]})]}),',
    'Object(ve.jsx)("span",{style:{flexShrink:0,background:"#312e81",color:"#fff",',
    'fontWeight:600,padding:"9px 18px",borderRadius:8,fontSize:".92rem"},',
    'children:"My requests"})]})}),',
]
card = "".join(card_parts).encode("utf-8")

new = data.replace(anchor, anchor + card, 1)
open(OUT, "wb").write(new)
print("patched:", len(new), "orig:", len(data), "card:", len(card))
