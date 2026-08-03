"""Manuel dogrulama scripti: tri_format paketini gercek .tri dosyalarina
karsi calistirir ve neyin cozulup neyin cozulmedigini raporlar.

Calistirmak icin (repo kok dizininden):
    python nomad/plugins/test_tri_format_manual.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "instrument_data"))

from tri_format import parse_tri_file, verify_full_coverage  # noqa: E402

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample_files")
SAMPLE_FILES = [
    os.path.join(SAMPLE_DIR, "TGA_AC1BAPO UV CURED 1Kmin1000CN2MS.tri"),
    os.path.join(SAMPLE_DIR, "DMA_PTDB_30AC_1BAPO UV CURED AS B.tri"),
]

for path in SAMPLE_FILES:
    print("=" * 80)
    print("DOSYA:", path)
    try:
        result = parse_tri_file(path)
    except Exception as exc:
        print("PARSE BASARISIZ:", type(exc).__name__, exc)
        continue

    print("\n--- Basliktan okunan metadata ---")
    for field_name, value in vars(result.header).items():
        print(f"  {field_name}: {value}")

    print("\n--- Bolumler (sections) ---")
    total_size = os.path.getsize(path)
    for s in result.sections:
        pct = s.length / total_size * 100
        print(f"  {s.name:20s} offset={s.offset:>10} length={s.length:>10} (%{pct:.1f})")

    print("\n--- Uyarilar ---")
    for w in result.warnings:
        print(" ", w)

    try:
        verify_full_coverage(result, total_size)
        print("\nBYTE KAPSAMA KONTROLU: BASARILI (dosyanin her byte'i hesaba katildi)")
    except AssertionError as exc:
        print("\nBYTE KAPSAMA KONTROLU: BASARISIZ ->", exc)
    print()
