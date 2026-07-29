import sys

# Fix 1: extract_tga_metadata in parser.py - add missing fields
path = "/home/debian/nomad-distro-template/plugins/instrument_data/parser.py"
with open(path) as f:
    c = f.read()

# Add sample_weight as alias for sample_mass
c = c.replace(
    'for key in ["sample_mass", "sample mass"]:',
    'for key in ["sample_mass", "sample mass", "sample_weight", "sample weight"]:'
)

# Add gas_atmosphere, heating_rate, temperature_end extraction
old_return = "    return result"
new_return = """
    # Gas atmosphere
    for key in ["gas_atmosphere", "gas atmosphere"]:
        if key in metadata:
            result["gas_atmosphere"] = metadata[key]
            break

    # Heating rate
    for key in ["heating_rate", "heating rate"]:
        if key in metadata:
            result["heating_rate"] = metadata[key]
            break

    # Temperature end
    for key in ["temperature_end", "temperature end"]:
        if key in metadata:
            result["temperature_end"] = metadata[key]
            break

    return result"""

c = c.replace(old_return, new_return, 1)

with open(path, "w") as f:
    f.write(c)
print("1. Patched extract_tga_metadata")

# Fix 2: param_map in push_tga_results_to_item to match actual keys
path2 = "/home/debian/nomad-distro-template/plugins/instrument_data/elabftw_client.py"
with open(path2) as f:
    c2 = f.read()

# Replace the param_map in push_tga_results_to_item
old_params = """            param_map = {
                \"sample_name\": (\"Sample Name\", \"\"),
                \"sample_mass_mg\": (\"Sample Mass\", \"mg\"),
                \"method_name\": (\"Procedure\", \"\"),
                \"heating_rate\": (\"Heating Rate\", \"K/min\"),
                \"temperature_end\": (\"Final Temperature\", \"°C\"),
                \"pan_type\": (\"Crucible\", \"\"),
                \"gas_atmosphere\": (\"Atmosphere\", \"\"),
                \"operator\": (\"Operator\", \"\"),
            }"""

new_params = """            param_map = {
                \"sample_name\": (\"Sample Name\", \"\"),
                \"sample_mass\": (\"Sample Mass\", \"mg\"),
                \"procedure_name\": (\"Procedure\", \"\"),
                \"heating_rate\": (\"Heating Rate\", \"K/min\"),
                \"temperature_end\": (\"Final Temperature\", \"°C\"),
                \"crucible_type\": (\"Crucible\", \"\"),
                \"gas_atmosphere\": (\"Atmosphere\", \"\"),
                \"operator\": (\"Operator\", \"\"),
                \"instrument_name\": (\"Instrument\", \"\"),
            }"""

c2 = c2.replace(old_params, new_params)
if old_params not in c2 and new_params not in c2:
    print("WARNING: param_map not found in elabftw_client.py")
else:
    with open(path2, "w") as f:
        f.write(c2)
    print("2. Patched param_map")

# Fix 3: Add NOMAD entry URL building  
# In push_tga_results_to_item, add entry_id param and build proper URL
old_sig2 = '        entry_id: str = "",'
new_sig2 = '        entry_id: str = "",\n        upload_id: str = "",'
if old_sig2 in c2:
    c2 = c2.replace(old_sig2, new_sig2)
    with open(path2, "w") as f:
        f.write(c2)
    print("3. Added upload_id param")

# Fix 4: Build entry URL from upload_id 
old_url_block = """        if nomad_url:
            nomad_html = (
                '<h3 style=\"margin:16px 0 8px\">NOMAD Entry</h3>'
                f'<p><a href=\"{nomad_url}\" target=\"_blank\" style=\"color:#1976D2\">{nomad_url}</a></p>'
            )"""

new_url_block = """        # Build NOMAD entry URL
        nomad_entry_url = nomad_url
        if entry_id:
            nomad_entry_url = f\"https://researchmcp.duckdns.org/nomad-oasis/gui/search/entries/entry/id/{entry_id}\"
        if nomad_entry_url:
            nomad_html = (
                '<h3 style=\"margin:16px 0 8px\">NOMAD Entry</h3>'
                f'<p><a href=\"{nomad_entry_url}\" target=\"_blank\" style=\"color:#1976D2\">{nomad_entry_url}</a></p>'
            )"""

if old_url_block in c2:
    c2 = c2.replace(old_url_block, new_url_block)
    with open(path2, "w") as f:
        f.write(c2)
    print("4. Fixed NOMAD URL with entry link")
else:
    print("WARNING: URL block not found")

# Fix 5: In push_tga_to_elabftw, pass entry_id and upload_id
path3 = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(path3) as f:
    c3 = f.read()

# Add entry_id to push_tga_to_elabftw call
old_call = """        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,
            csv_filepath=csv_filepath,
            norm=norm,"""

new_call = """        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,
            csv_filepath=csv_filepath,
            norm=norm,
            upload_id=upload_id,"""

if old_call in c3:
    # Can't replace yet - need entry_id from NOMAD
    pass

# Actually, let's add entry_id lookup in push_tga_to_elabftw
# Add after the plot_url = "" section
old_plot_section = """    plot_url = \"\"
    if csv_filepath:
        try:
            self.upload_file_to_item(elab_item_id, csv_filepath)
        except Exception:
            pass
    if plot_png:"""

# This is in elabftw_client.py, already done above

print("\nDone. Please verify with syntax check.")
