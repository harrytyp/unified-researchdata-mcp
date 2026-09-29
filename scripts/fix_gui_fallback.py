
import io, sys

path = "/home/debian/unified-researchdata-mcp/nomad/configs/nginx_base_conf"
with io.open(path, "r", encoding="utf-8", newline="") as fh:
    text = fh.read()

old = """location @redirect_to_index {
    rewrite ^ /nomad-oasis/gui/index.html break;
    proxy_pass http://$nomad_app$request_uri;
}"""

new = """location @redirect_to_index {
    rewrite ^ /nomad-oasis/gui/index.html break;
    # $request_uri would still carry the original path, so the rewrite above is
    # lost and the app answers 404 again (the GUI root and every SPA deep link
    # ended in nginx's own 404). $uri is the rewritten one.
    proxy_pass http://$nomad_app$uri$is_args$args;
}"""

if "$uri$is_args$args" in text:
    print("already patched")
    sys.exit(0)
if old not in text:
    print("ANCHOR NOT FOUND")
    sys.exit(1)

with io.open(path, "w", encoding="utf-8", newline="") as fh:   # same inode: bind-mounted
    fh.write(text.replace(old, new, 1))
print("patched in place")
