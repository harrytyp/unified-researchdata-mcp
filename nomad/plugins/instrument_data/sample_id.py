"""Short sample id: the first characters of the NOMAD upload_id.

Why this exists: the requester has to be able to label the physical sample as
soon as the request is submitted, and that label has to be recognisable in the
operator app and in NOMAD. Every NOMAD access already keys on the upload_id -
it is created by the submit itself, never changes, and appears in the .tprc,
the entry, the entry metadata and the GUI URL - so no new id is introduced.
It is only too long to write by hand (22 characters, mixed case), so the first
characters are shown as the human-facing code.

The code is prefixed to the sample name that goes into the generated .tprc, so
TRIOS reports it back with the measurement (Sample.Name -> result_sample_name)
and the round trip is unambiguous - sample names are not unique, the code is.

IMPORTANT: SAMPLE_ID_LEN is mirrored in tga/tga-forms/app.py and in
tga/tga_v2/ui_common.py. Keep all three in sync.
"""

SAMPLE_ID_LEN = 5


def sample_id(upload_id: str | None) -> str:
    """Short, hand-writable form of a NOMAD upload_id ('' if none)."""
    return (upload_id or '')[:SAMPLE_ID_LEN]
