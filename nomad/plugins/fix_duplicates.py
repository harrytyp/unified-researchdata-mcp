import sys

p = "/home/debian/nomad-distro-template/plugins/instrument_data/processor.py"
with open(p) as f:
    content = f.read()

# Count norm=norm occurrences after line 300
count = 0
lines = content.split("\n")
for i, line in enumerate(lines):
    if "norm=norm," in line and i > 300:
        count += 1

if count > 1:
    # Replace all but keep only one
    # Strategy: replace ALL instances of "norm=norm,\n" with "" except one at the right place
    first = True
    new_lines = []
    for line in lines:
        if "norm=norm," in line:
            if first:
                new_lines.append(line)
                first = False
            else:
                continue  # skip duplicates
        else:
            new_lines.append(line)
    with open(p, "w") as f:
        f.write("\n".join(new_lines))
    print(f"Removed {count-1} duplicate norm=norm lines")
else:
    print(f"Only {count} norm=norm lines, no duplicates")

# Verify
with open(p) as f:
    c = f.read()
    occ = c.count("norm=norm,")
    print(f"Total norm=norm occurrences: {occ}")
