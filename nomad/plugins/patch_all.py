import sys

# ========== 1. Add csv_filepath and norm params to push_tga_results_to_item ==========
path = "/home/debian/nomad-distro-template/plugins/instrument_data/elabftw_client.py"
with open(path) as f:
    c = f.read()

# Add Optional import if not present
if "from typing import" in c and "Optional" not in c.split("from typing import")[1].split("\n")[0]:
    c = c.replace("from typing import", "from typing import Optional, ")
elif "from typing import Optional" not in c:
    # Add to imports
    c = c.replace("from typing import", "from typing import Optional, ")

# Patch signature
c = c.replace(
    "plot_url: str = \"\",\n    ) -> bool:",
    "plot_url: str = \"\",\n        csv_filepath: str = \"\",\n        norm: Optional[Dict[str, Any]] = None,\n    ) -> bool:"
)

# Upload CSV before plot
c = c.replace(
    "plot_url = \"\"\n    if plot_png:",
    "plot_url = \"\"\n    if csv_filepath:\n        try:\n            self.upload_file_to_item(elab_item_id, csv_filepath)\n        except Exception:\n            pass\n    if plot_png:"
)

with open(path, "w") as f:
    f.write(c)
print("1. Patched elabftw_client.py")

# ========== 2. Add parameters section to body in push_tga_results_to_item ==========
# Add before the progress bar section
params_block = """
        # Measurement parameters table
        params_html = \"\"
        if norm:
            param_rows = []
            param_map = {
                \"sample_name\": (\"Sample Name\", \"\"),
                \"sample_mass_mg\": (\"Sample Mass\", \"mg\"),
                \"method_name\": (\"Procedure\", \"\"),
                \"heating_rate\": (\"Heating Rate\", \"K/min\"),
                \"temperature_end\": (\"Final Temperature\", \"°C\"),
                \"pan_type\": (\"Crucible\", \"\"),
                \"gas_atmosphere\": (\"Atmosphere\", \"\"),
                \"operator\": (\"Operator\", \"\"),
            }
            for key, (label, unit) in param_map.items():
                val = norm.get(key)
                if val:
                    display = f\"\"\"{val} {unit}\"\"\" if unit else str(val)
                    param_rows.append(
                        \"<tr><td style=\\\"padding:4px 12px;font-weight:600;color:#555;white-space:nowrap\\\">\" + label + \"</td>\"
                        \"<td style=\\\"padding:4px 12px\\\">\" + display + \"</td></tr>\"
                    )
            if param_rows:
                params_html = (
                    \"<h3 style=\\\"margin:16px 0 8px\\\">Measurement Parameters</h3>\"
                    \"<table style=\\\"border-collapse:collapse;width:auto;font-size:13px;margin:4px 0\\\">\"
                    + \"\".join(param_rows)
                    + \"</table>\"
                )

        # Progress bar"""

c2 = c.replace(
    "        # Progress bar",
    params_block
)

with open(path, "w") as f:
    f.write(c2)
print("2. Added parameters section to body")

# ========== 3. Add params_html to body assembly ==========
c3 = open(path).read()
c3 = c3.replace(
    "f\"{progress_html}\"\n            f\"{steps_html}\"",
    "f\"{params_html}\"\n            f\"{progress_html}\"\n            f\"{steps_html}\""
)
with open(path, "w") as f:
    f.write(c3)
print("3. Added params_html to body")

# ========== 4. Patch processor.py to pass norm and csv_filepath ==========
path2 = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(path2) as f:
    c4 = f.read()

# In process_tga_file, push to elabFTW call - add csv_filepath and norm
c4 = c4.replace(
    "push_tga_to_elabftw(\n            elab_item_id=elab_item_id,\n            sample_name=sample_name,\n            signals=signals,\n            computed=computed,\n            nomad_url=nomad_url,\n            plot_png=plot_png,\n            elabftw_api_key=elabftw_api_key,\n            elabftw_team=elabftw_team,\n            upload_id=upload_id,",
    "push_tga_to_elabftw(\n            elab_item_id=elab_item_id,\n            sample_name=sample_name,\n            signals=signals,\n            computed=computed,\n            nomad_url=nomad_url,\n            plot_png=plot_png,\n            elabftw_api_key=elabftw_api_key,\n            elabftw_team=elabftw_team,\n            upload_id=upload_id,\n            csv_filepath=str(path),\n            norm=norm,"
)

# In push_tga_to_elabftw - add csv_filepath and norm to function signature
c4 = c4.replace(
    "def push_tga_to_elabftw(\n    elab_item_id: int,\n    sample_name: str,\n    signals: Dict[str, List[float]],\n    computed: Dict[str, Any],\n    nomad_url: str,\n    plot_png: Optional[bytes] = None,\n    elabftw_api_url: str = DEFAULT_ELABFTW_URL,\n    elabftw_api_key: str = \"\",\n    elabftw_team: int = DEFAULT_ELABFTW_TEAM,\n    upload_id: str = \"\",",
    "def push_tga_to_elabftw(\n    elab_item_id: int,\n    sample_name: str,\n    signals: Dict[str, List[float]],\n    computed: Dict[str, Any],\n    nomad_url: str,\n    plot_png: Optional[bytes] = None,\n    elabftw_api_url: str = DEFAULT_ELABFTW_URL,\n    elabftw_api_key: str = \"\",\n    elabftw_team: int = DEFAULT_ELABFTW_TEAM,\n    upload_id: str = \"\",\n    csv_filepath: str = \"\",\n    norm: Optional[Dict[str, Any]] = None,"
)

# In push_tga_to_elabftw - pass csv_filepath and norm to elab.push_tga_results_to_item
c4 = c4.replace(
    "ok = elab.push_tga_results_to_item(\n            item_id=elab_item_id,\n            sample_name=sample_name,\n            signals=signals,\n            computed=computed,\n            nomad_url=nomad_url,\n            plot_url=plot_url,",
    "ok = elab.push_tga_results_to_item(\n            item_id=elab_item_id,\n            sample_name=sample_name,\n            signals=signals,\n            computed=computed,\n            nomad_url=nomad_url,\n            plot_url=plot_url,\n            csv_filepath=csv_filepath,\n            norm=norm,"
)

with open(path2, "w") as f:
    f.write(c4)
print("4. Patched processor.py")

print("\nAll done!")
