import requests, time, json, glob, os, msgpack, warnings
warnings.filterwarnings("ignore")

PAT = open("/app/.nomad_pat").read().strip()
ELAB_KEY = None
for fn in ["/app/plugins/.elabftw_api_key", "/app/elabftw_key.txt"]:
    if os.path.exists(fn):
        ELAB_KEY = open(fn).read().strip()
        break
if not ELAB_KEY:
    ELAB_KEY = os.environ.get("ELABFTW_API_KEY")
print("ELAB key length:", len(ELAB_KEY) if ELAB_KEY else 0)

h_nomad = {"Authorization": "Bearer " + PAT}
h_elab = {"Authorization": ELAB_KEY, "Content-Type": "application/json"}

print("=" * 60)
print("FINAL E2E - Bidirectional linking test")
print("=" * 60)

# 1. Create elabFTW item
print("\n[1] Creating elabFTW item...")
ts = time.strftime("%H%M%S")
cr = requests.post("https://elntest.ub.tum.de/api/v2/items", headers=h_elab,
    json={"title": "TGA_REF_" + ts, "category": "5", "status": "67"},
    verify=False, timeout=15)
item_id = int(cr.headers["Location"].split("/")[-1])
print("  Item " + str(item_id))

# 2. Upload xlsx
print("\n[2] Uploading real xlsx to NOMAD...")
xlsx = "/app/plugins/sample_files/TGA_AC1BAPO UV CURED 5KMIN 1000C N2.xlsx"
fname = "TGA_REF_item" + str(item_id) + ".xlsx"
with open(xlsx, "rb") as f:
    raw = f.read()
r = requests.post("http://localhost:8000/nomad-oasis/api/v1/uploads", headers=h_nomad,
    files={"file": (fname, raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    timeout=15)
print("  Upload " + str(r.status_code))
time.sleep(5)
ru = requests.get("http://localhost:8000/nomad-oasis/api/v1/uploads?order=desc&per_page=2", headers=h_nomad, timeout=10)
uid = ru.json()["data"][0]["upload_id"]
print("  UID " + uid)

# 3. Wait for parser
print("\n[3] Waiting for NOMAD parser...")
for i in range(18):
    time.sleep(10)
    ru = requests.get("http://localhost:8000/nomad-oasis/api/v1/uploads/" + uid, headers=h_nomad, timeout=10)
    u = ru.json().get("data", ru.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print("  " + str(i) + ": " + proc + " e=" + str(ent))
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

# 4. Check archive for elabFTW reference
print("\n[4] Checking archive...")
ad = "/app/.volumes/fs/staging/" + uid[:2] + "/" + uid + "/archive"
msg = glob.glob(os.path.join(ad, "*.msg"))
if msg:
    eid = os.path.basename(msg[0]).split("-")[0]
    print("  Entry ID: " + eid)
    with open(msg[0], "rb") as f:
        unpacker = msgpack.Unpacker(f)
        for obj in unpacker:
            if isinstance(obj, dict) and "data" in obj:
                eeid = list(obj["data"].keys())[0]
                ea = obj["data"][eeid]
                if isinstance(ea, dict) and "data" in ea:
                    d2 = ea["data"]
                    m = d2.get("metadata", {})
                    if isinstance(m, dict):
                        refs = m.get("references", "NONE")
                        print("  references: " + str(refs))
                        errs = m.get("processing_errors", [])
                        print("  errors: " + str(len(errs)))
                break
else:
    eid = "N/A"
    print("  No archive")

print("\n" + "=" * 60)
print("elabFTW:     https://elntest.ub.tum.de/database.php?mode=view&id=" + str(item_id))
print("NOMAD:       https://researchmcp.ducknss.org/nomad-oasis/gui/search/entries/entry/id/" + eid)
