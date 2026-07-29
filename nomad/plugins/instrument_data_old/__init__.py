"""Instrument data schemas for NOMAD Oasis.

Note: The parser and elabftw_client modules can be imported standalone
(without NOMAD dependencies). The schema module requires nomad package.
"""
# Only import schema when running inside NOMAD context
from instrument_data.parser import parse_file, detect_format
from instrument_data.elabftw_client import ElabftwClient

__all__ = [
    "parse_file",
    "detect_format",
    "ElabftwClient",
]
