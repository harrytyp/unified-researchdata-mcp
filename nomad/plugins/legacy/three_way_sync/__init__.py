"""
Three-way Sync: elabFTW ↔ NOMAD ↔ DataTagger.

NOMAD ELN schema + normalizer for automatic bidirectional linking between
elabFTW experiments and NOMAD entries.

Schemas:
  - ElabftwLinkedEntry: Store elabFTW refs, auto-link on save
  - ElabftwMachineUpload: For machine uploads that create elabFTW experiments
"""
from three_way_sync.schema import ElabftwLinkedEntry, ElabftwMachineUpload
from three_way_sync.normalizer import normalize

__all__ = ["ElabftwLinkedEntry", "ElabftwMachineUpload", "normalize"]
