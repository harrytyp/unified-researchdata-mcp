"""Reapply all processor.py patches cleanly after git restore."""
import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(path) as f:
    c = f.read()

# 1. Add import os after import re
c = c.replace("import re\n", "import re\nimport os\nimport glob\n")

# 2. Add csv_filepath, norm, entry_id to push_tga_to_elabftw signature
c = c.replace(
    "    upload_id: str = \"\",",
    "    upload_id: str = \"\",\n    csv_filepath: str = \"\",\n    norm: Optional[Dict[str, Any]] = None,\n    entry_id: str = \"\","
)

# 3. Add csv_filepath, norm, entry_id to the elab.push_tga_results_to_item call
old_call = """        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,"""

new_call = """        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,
            csv_filepath=csv_filepath,
            norm=norm,
            entry_id=entry_id,
            upload_id=upload_id,"""

c = c.replace(old_call, new_call, 1)

# 4. Remove the old upload_id=upload_id from the elab call (now in new_call)
c = c.replace(
    "            entry_id=entry_id,\n            upload_id=upload_id,\n        )\n    except Exception:\n        ok = False",
    "        )\n    except Exception:\n        ok = False"
)

# 5. Add entry_id lookup in process_tga_file 
old_step5 = """    # 5. Push to elabFTW
    if elab_item_id and elabftw_api_key:
        success, elab_url = push_tga_to_elabftw(
            elab_item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_png=plot_png,
            elabftw_api_key=elabftw_api_key,
            elabftw_team=elabftw_team,
            upload_id=upload_id,"""

new_step5 = """    # Look up NOMAD entry ID from archive files
    entry_id = ""
    if upload_id:
        archive_dir = f"/app/.volumes/fs/staging/{upload_id[:2]}/{upload_id}/archive"
        msg_files = glob.glob(os.path.join(archive_dir, "*.msg"))
        if msg_files:
            entry_id = os.path.basename(msg_files[0]).split("-")[0]

    # 5. Push to elabFTW
    if elab_item_id and elabftw_api_key:
        success, elab_url = push_tga_to_elabftw(
            elab_item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_png=plot_png,
            elabftw_api_key=elabftw_api_key,
            elabftw_team=elabftw_team,
            upload_id=upload_id,
            csv_filepath=str(path),
            norm=norm,
            entry_id=entry_id,"""

c = c.replace(old_step5, new_step5, 1)

with open(path, "w") as f:
    f.write(c)

# Verify
import subprocess
result = subprocess.run(
    ["python3", "-c", 
     "import sys; sys.path.insert(0,\"/home/debian/nomad-distro-template/plugins\"); "
     "from instrument_data.processor import process_tga_file, push_tga_to_elabftw; "
     "from instrument_data.elabftw_client import ElabftwClient; print(\"OK\")"],
    capture_output=True, text=True, timeout=10
)
print(result.stdout.strip())
if result.stderr:
    print("ERROR:", result.stderr[:200])
