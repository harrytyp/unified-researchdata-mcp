
import re, subprocess, sys, os
os.chdir("/home/debian/unified-researchdata-mcp")
files = ["Caddyfile", "docker-compose.yml", ".env.example", "nomad/configs/nginx_base_conf"]
diff = subprocess.run(["git","diff","HEAD","--"]+files, capture_output=True, text=True).stdout
suspicious = []
patterns = [
    re.compile(r"[0-9a-f]{32,}", re.I),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"[A-Za-z0-9_\-]{40,}"),
]
for line in diff.splitlines():
    if not line.startswith("+"):
        continue
    body = line[1:]
    for p in patterns:
        for m in p.finditer(body):
            value = m.group(0)
            # placeholders, variable references and hashes of images are fine
            if value.startswith(("${", "sha256:", "dryRun-")) or value.isdigit():
                continue
            if re.fullmatch(r"[0-9a-f]+", value) and len(value) <= 64:
                continue
            suspicious.append((p.pattern, value[:40], body.strip()[:80]))
print("=== suspicious additions in the diff:", len(suspicious))
for s in suspicious[:15]:
    print("  ", s)
print()
print("=== untracked nomad-mcp files: any literal secret? ===")
out = subprocess.run(["grep","-rInE","[0-9a-f]{32,}|nomad_pat_[A-Za-z0-9]+|sk-[A-Za-z0-9]{20,}","nomad-mcp/"],
                     capture_output=True, text=True).stdout
print(out or "  none")
print("=== does .env.example carry a value for the new keys? ===")
out = subprocess.run(["grep","-n","NOMAD_MCP"," .env.example"], capture_output=True, text=True, shell=False).stdout
out = subprocess.run(["grep","-n","NOMAD_MCP",".env.example"], capture_output=True, text=True).stdout
print(out or "  none")
