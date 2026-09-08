#!/usr/bin/env python3
"""Check last uploads and their parsers."""
import requests, time, warnings
warnings.filterwarnings("ignore")
PAT = open("/app/.nomad_pat").read().strip()
h = {"Authorization": "Bearer " + PAT}
URL = "http://localhost:8000/nomad-oasis/api/v1/uploads"

r = requests.get(URL + "?order=desc&per_page=5", headers=h, timeout=10)
for u in r.json().get("data", []):
    fn = u.get("filename", "?")
    ent = u.get("entries", 0)
    parser = u.get("parser", "")
    print(fn, "entries=", ent, "parser=", parser)
