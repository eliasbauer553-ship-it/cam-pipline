"""
Reproduziert exakt das Beispiel aus der Pipeline-Skizze:

    Sony α7 IV
    Sony A7 IV
    ILCE-7M4
          ↓
    Sony Alpha 7 IV

Läuft ohne Netzwerk, ohne pytest — einfach: python3 tests/test_normalizer_example.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stage3_normalizer import normalize_record  # noqa: E402


def make_wikidata_rec(label, manufacturer="Sony"):
    return {"_source": "wikidata", "label_raw": label, "manufacturer_raw": manufacturer,
            "image_url": None, "release_date": None, "mount_raw": None}


def make_sensor_db_rec(vendor, model):
    return {"_source": "camera_sensor_db", "vendor_raw": vendor, "model_raw": model, "sensor_modes": {}}


def main():
    cases = [
        make_wikidata_rec("Sony α7 IV"),
        make_wikidata_rec("Sony A7 IV"),
        make_sensor_db_rec("Sony", "ILCE-7M4"),
    ]
    results = [normalize_record(c) for c in cases]

    print("Eingabe -> normalisiert:")
    for rec, res in zip(cases, results):
        raw = rec.get("label_raw") or rec.get("model_raw")
        print(f"  {raw!r:20} -> {res['canonical_name_candidate']!r}")

    names = {r["canonical_name_candidate"] for r in results}
    assert names == {"Sony Alpha 7 IV"}, f"FEHLGESCHLAGEN — verschiedene Kanonisierungen: {names}"
    print("\nOK: Alle drei Schreibweisen wurden auf 'Sony Alpha 7 IV' vereinheitlicht.")


if __name__ == "__main__":
    main()
