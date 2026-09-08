import requests, time, glob, os, sys, warnings
warnings.filterwarnings("ignore")

PAT = open("/app/.nomad_pat").read().strip()
API=open("/app/plugins/elab_key.txt").read().strip()
h_nomad = {"Authorization": "Bearer " + PAT}
h_elab = {"Authorization": API, "Content-Type": "application/json"}

ts = time.strftime("%H%M%S")
cr = requests.post("https://elntest.ub.tum.de/api/v2/items", headers=h_elab,
    json={"title": "TGATEST_" + ts, "category": "145", "status": "67"},
    verify=False, timeout=15)
item_id = int(cr.headers["Location"].split("/")[-1])
print("Item", item_id)

xlsx = "/app/plugins/sample_files/TGA_AC1BAPO UV CURED 5KMIN 1000C N2.xlsx"
fname = "TGATEST_item" + str(item_id) + ".xlsx"
with open(xlsx, "rb") as f:
    raw = f.read()
r = requests.post("http://localhost:8000/nomad-oasis/api/v1/uploads", headers=h_nomad,
    files={"file": (fname, raw)}, timeout=15)
print("Upload", r.status_code)

for i in range(18):
    time.sleep(10)
    ru = requests.get("http://localhost:8000/nomad-oasis/api/v1/uploads?order=desc&per_page=2", headers=h_nomad, timeout=10)
    uid = ru.json()["data"][0]["upload_id"]
    ru2 = requests.get("http://localhost:8000/nomad-oasis/api/v1/uploads/" + uid, headers=h_nomad, timeout=10)
    u = ru2.json().get("data", ru2.json())
    proc = u.get("process_status", "?")
    ent = u.get("entries", 0)
    run = u.get("process_running", False)
    print(i, proc, "e=", ent)
    if not run and proc in ("SUCCESS", "FAILURE"):
        break

ad = "/app/.volumes/fs/staging/" + uid[:2] + "/" + uid + "/archive"
msg = glob.glob(os.path.join(ad, "*.msg"))
if msg:
    eid = os.path.basename(msg[0]).rsplit("-v", 1)[0]
    print("EID", eid)
    sys.path.insert(0, "/app/plugins")
    from instrument_data.processor import process_tga_file
    rd = "/app/.volumes/fs/staging/" + uid[:2] + "/" + uid + "/raw"
    files = os.listdir(rd)
    fp = os.path.join(rd, files[0])
    res = process_tga_file(filepath=fp, elab_item_id=item_id,
        upload_id=uid, elabftw_api_key=API, elabftw_team=29)
    print("Push:", res.get("status"))

ru = requests.get("https://elntest.ub.tum.de/api/v2/items/" + str(item_id), headers=h_elab, verify=False, timeout=15)
b = ru.json().get("body") or ""
print("Body len:", len(b))
if len(b) > 10:
    for s in ["Parameters", "Raw", "NOMAD Entry", "Residue"]:
        print("  " + s + ":", s in b)
else:
    print("SHORT BODY:", b[:60])

print("elabFTW: https://elntest.ub.tum.de/database.php?mode=view&id=" + str(item_id))
print("NOMAD: https://researchmcp.ducknss.org/nomad-oasis/gui/search/entries/entry/id/" + eid)
