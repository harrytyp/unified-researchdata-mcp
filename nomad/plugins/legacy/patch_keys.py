import sys

path = "/home/debian/nomad-distro-template/plugins/instrument_data/elabftw_client.py"
with open(path) as f:
    c = f.read()

# Fix 1: computed keys - onset_temperature -> onset_temperature_c
c = c.replace(
    'onset = computed.get("onset_temperature", "")',
    'onset = computed.get("onset_temperature_c", "")'
)
# Also fix the second occurrence (in push_tga_results for experiments)
c = c.replace(
    'onset = computed.get("onset_temperature", "")',
    'onset = computed.get("onset_temperature_c", "")'
)

# Fix 2: Add our signal names to col_map (add after "tan_delta" line)
old_colmap_end = '            "tan_delta": "Tan \\u03b4",\n        }'
new_colmap_end = '            "tan_delta": "Tan \\u03b4",\n            # TRIOS TGA export column names\n            "temp./c": "Temp (\\u00b0C)",\n            "value/mg": "Weight (mg)",\n            "sample_weight/mg": "Sample Weight (mg)",\n            "time/min": "Time (min)",\n            "time/s": "Time (s)",\n            "index": "Index",\n            "delta/c/min": "Delta T/min",\n            "weight_pct": "Weight (%)",\n            "dta": "DTA (\\u00b0C)",\n        }'

c = c.replace(old_colmap_end, new_colmap_end, 1)

with open(path, "w") as f:
    f.write(c)
print("Patched elabftw_client.py")
