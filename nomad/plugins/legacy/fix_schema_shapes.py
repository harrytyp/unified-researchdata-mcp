"""Fix schema.py - add shape only to TGA JSON quantities, not to all."""
import sys

path = "/app/plugins/instrument_data/schema.py"
with open(path) as f:
    c = f.read()

# Only add shape to TGA quantities, skip DMA/FTIR/MS
tga_quantities = [
    ("temperature_signal", "description=\\\"Temperature array [°C]\\\""),
    ("weight_signal", "description=\\\"Weight array [mg]\\\""),
    ("dta_signal", "description=\\\"DTA signal\\\""),
]

for name, desc in tga_quantities:
    old = f"{name} = Quantity(\n        type=JSON,\n        {desc})"
    new = f"{name} = Quantity(\n        type=JSON,\n        shape=[\"*\"],\n        {desc})"
    c = c.replace(old, new)

with open(path, "w") as f:
    f.write(c)
print("Fixed shapes")
