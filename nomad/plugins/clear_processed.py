import sys
sys.path.insert(0, "/app/plugins")
from nomad_processor import load_processed, save_processed

procd = load_processed()
print(f"Processed: {len(procd)} uploads")
save_processed("", set())
print("Cleared processed log")
