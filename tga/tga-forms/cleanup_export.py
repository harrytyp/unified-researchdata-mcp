"""Drop the stored export entries of one experiment (used by the UI test)."""
import sys

sys.path.insert(0, "/app")

from notify import settings as settings_mod  # noqa: E402

gone = sys.argv[1] if len(sys.argv) > 1 else ""
data = settings_mod.load_exports()
removed = 0
for key, items in list(data.items()):
    kept = [item for item in items if str(item.get("id")) != gone]
    removed += len(items) - len(kept)
    data[key] = kept
settings_mod._write_json(settings_mod.EXPORTS_FILE, data)
print(f"Eintraege fuer Experiment {gone} entfernt: {removed}")
