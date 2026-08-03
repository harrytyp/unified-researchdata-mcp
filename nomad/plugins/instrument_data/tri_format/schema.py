"""Declarative mapping: raw .tri header keys -> TriHeaderFields attributes.

THIS is the file to edit when the file format changes -- a new TRIOS
version renaming/adding/removing a header key, or a newly discovered
field. No other module (cursor.py, sections/header.py, registry.py)
needs to change for that kind of update.

Order matters only in that it mirrors the order TRIOS actually writes
these keys (documented for readability, not required for correctness --
sections/header.py maps by key name, not position).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    raw_key: str      # exact key string as it appears in the .tri file
    attr: str          # target attribute name on TriHeaderFields
    required: bool = False  # missing -> warning in ParsedTriFile.warnings, never a crash


HEADER_SCHEMA = [
    FieldSpec("instrumenttype", "instrument_type", required=True),
    FieldSpec("instrumentserialnumber", "instrument_serial_number"),
    FieldSpec("instrumentname", "instrument_name"),
    FieldSpec("companyname", "company_name"),
    FieldSpec("rundate", "run_date"),
    FieldSpec("operator", "operator"),
    FieldSpec("project", "project"),
    FieldSpec("samplename", "sample_name", required=True),
    FieldSpec("comments", "comments"),
    FieldSpec("pantype", "pan_type"),
    FieldSpec("samplepannumber", "pan_number"),
    FieldSpec("procedurename", "procedure_name"),
    FieldSpec("proceduresegments", "procedure_segments"),
    FieldSpec("proceduresignals", "procedure_signals"),
    FieldSpec("procedureGUID", "procedure_guid"),
]

# The first key expected in the file -- used as the anchor to locate
# where the header TLV region begins (see sections/header.py). If a
# future TRIOS version renames this too, change it here.
HEADER_ANCHOR_KEY = "instrumenttype"

# --------------------------------------------------------------------
# EXAMPLE: adapting to a hypothetical future format change.
#
# Say a new TRIOS version starts writing an actual "samplemassmg" key
# with a numeric-looking string value. To support it, the ONLY change
# needed anywhere in this package is adding one line here:
#
#   FieldSpec("samplemassmg", "sample_mass_mg"),
#
# ...plus adding the matching `sample_mass_mg: Optional[str] = None`
# attribute to TriHeaderFields in models.py. sections/header.py,
# cursor.py, and registry.py are completely untouched. Until that
# line is added, an unrecognized "samplemassmg" key would simply land
# in TriHeaderFields.extra_fields["samplemassmg"] instead of being
# lost -- so nothing breaks even before the schema is updated.
# --------------------------------------------------------------------
