import sys, os

# Fix processor.py - add entry_id lookup and pass to push
path = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(path) as f:
    c = f.read()

# 1. Add csv_filepath and norm to push_tga_to_elabftw signature
c = c.replace(
    "    upload_id: str = \"\",",
    "    upload_id: str = \"\",\n    csv_filepath: str = \"\",\n    norm: Optional[Dict[str, Any]] = None,"
)

# 2. Add entry_id lookup after plot_url setup, before push call
old_elab_call = """    # Push results via the elabFTW client method
    try:
        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,"""

new_elab_call = """    # Look up NOMAD entry ID from archive files
    entry_id = ""
    if upload_id:
        try:
            import glob
            archive_dir = f"/app/.volumes/fs/staging/{upload_id[:2]}/{upload_id}/archive"
            msg_files = glob.glob(os.path.join(archive_dir, "*.msg"))
            if msg_files:
                entry_id = os.path.basename(msg_files[0]).split("-")[0]
        except Exception:
            pass

    # Push results via the elabFTW client method
    try:
        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,"""

c = c.replace(old_elab_call, new_elab_call, 1)

# 3. Add entry_id and csv_filepath to the elab call
c = c.replace(
    "            plot_url=plot_url,\n        )\n    except Exception:\n        ok = False",
    "            plot_url=plot_url,\n            csv_filepath=csv_filepath,\n            norm=norm,\n            entry_id=entry_id,\n            upload_id=upload_id,\n        )\n    except Exception:\n        ok = False"
)

# 4. Add entry_id to push_tga_results_to_item signature in elabftw_client.py
path2 = "/home/debian/nomad-distro-template/plugins/instrument_data/elabftw_client.py"
with open(path2) as f:
    c2 = f.read()

c2 = c2.replace(
    "        entry_id: str = \"\",",
    "        entry_id: str = \"\","
)

# 5. Fix the nomad_url block to use entry_id when available
old_url = """        if nomad_url:
            nomad_html = (
                '<h3 style=\"margin:16px 0 8px\">NOMAD Entry</h3>'
                f'<p><a href=\"{nomad_url}\" target=\"_blank\" style=\"color:#1976D2\">{nomad_url}</a></p>'
            )"""

new_url = """        nomad_link_url = nomad_url
        if entry_id:
            nomad_link_url = f\"https://researchmcp.duckdns.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}\"
        if nomad_link_url:
            nomad_html = (
                '<h3 style=\"margin:16px 0 8px\">NOMAD Entry</h3>'
                f'<p><a href=\"{nomad_link_url}\" target=\"_blank\" style=\"color:#1976D2\">{nomad_link_url}</a></p>'
            )"""

c2 = c2.replace(old_url, new_url, 1)

with open(path, "w") as f:
    f.write(c)
print("1. Patched processor.py")

with open(path2, "w") as f:
    f.write(c2)
print("2. Patched elabftw_client.py")

# Verify
import subprocess
r = subprocess.run(["sudo", "docker", "exec", "nomad_oasis_app", "python3", "-c",
    "import sys; sys.path.insert(0,\"/app/plugins\"); from instrument_data.processor import push_tga_to_elabftw; from instrument_data.elabftw_client import ElabftwClient; print(\"OK\")"],
    capture_output=True, text=True, timeout=10)
print(r.stdout.strip())
if r.stderr:
    print("STDERR:", r.stderr[:200])
