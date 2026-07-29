# Attribution — Third-Party Code & Credits

This document clarifies which parts of this repository are original and which
are reused from third-party projects.

---

## Custom Code (Original, MIT License)

The following files were written for this project and are available under the
MIT license unless otherwise stated:

| File | Description | Author |
|------|-------------|--------|
| `docs/installation/*` | NOMAD Oasis deployment + elabFTW plugin install guide | Original |
| `docs/elabftw-integration/*` | Connection guide + user guide | Original |
| `plugins/elabftw_linker/__init__.py` | Package init | Original |
| `plugins/elabftw_linker/schema.py` | `ElabftwLinkedEntry` — custom ELN schema for dynamic elabFTW linking | Original |
| `plugins/elabftw_linker/normalizer.py` | Normalizer hook for auto-resolving cross-references | Original |
| `plugins/elabftw_linker/sync.py` | Standalone batch sync CLI | Original |

---

## Third-Party Code (Installed as Dependencies)

### nomad-external-eln-integrations

| Property | Value |
|----------|-------|
| **Source** | [`github.com/FAIRmat-NFDI/nomad-external-eln-integrations`](https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations) |
| **License** | Apache License 2.0 |
| **Author** | Amir Golparvar, FAIRmat-NFDI |
| **Installed via** | Git dependency in `pyproject.toml` |
| **What it provides** | `ElabftwProject` schema (online API sync), `ELabFTWParser` (offline .eln parsing), labfolder/chemotion/openBIS schemas |

This is the **base plugin** — it is NOT in this repository. It is pulled as a
dependency during the Docker build of the NOMAD Oasis image:

```toml
# pyproject.toml (on the Oasis server, not in this repo)
[project.optional-dependencies]
plugins = [
    "nomad-north-jupyter>=0.2.5",
    "nomad-external-eln-integrations @ git+https://github.com/FAIRmat-NFDI/nomad-external-eln-integrations.git",
]
```

The custom plugin in `plugins/elabftw_linker/` builds on top of this by
importing from `nomad.datamodel` and `nomad.search` — the same NOMAD SDK
classes that the FAIRmat plugin uses — but the schema and logic are original.

### NOMAD

| Property | Value |
|----------|-------|
| **Source** | [`github.com/FAIRmat-NFDI/nomad`](https://github.com/FAIRmat-NFDI/nomad) |
| **License** | Apache License 2.0 |
| **Author** | FAIRmat-NFDI / MPCDF |
| **Deployed via** | `nomad-distro-template` Docker image |

### NOMAD Distro Template

| Property | Value |
|----------|-------|
| **Source** | [`github.com/FAIRmat-NFDI/nomad-distro-template`](https://github.com/FAIRmat-NFDI/nomad-distro-template) |
| **License** | Apache License 2.0 |
| **Used for** | Docker Compose, Dockerfile, pyproject.toml base |

---

## Summary

| Component | Origin | License |
|-----------|--------|---------|
| NOMAD platform | FAIRmat-NFDI | Apache 2.0 |
| nomad-external-eln-integrations plugin | FAIRmat-NFDI | Apache 2.0 |
| nomad-distro-template (base config) | FAIRmat-NFDI | Apache 2.0 |
| **elabftw_linker custom plugin** | **This project** | **MIT** |
| **Documentation** | **This project** | **MIT** |
