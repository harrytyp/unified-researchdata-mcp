import sys
sys.path.insert(0, "/app/plugins")
for m in list(sys.modules.keys()):
    if "processor" in m:
        del sys.modules[m]
import inspect
from instrument_data.processor import push_tga_to_elabftw
src = inspect.getsource(push_tga_to_elabftw)
lines = src.split("\n")
for i in range(65, 85):
    print(f"{i}: {lines[i] if i < len(lines) else ''}")
