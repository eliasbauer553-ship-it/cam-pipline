"""
Prueft den Internet-Archive-Datum-Fallback OHNE echten Netzwerkzugriff —
gleiches Muster wie test_wikimedia_fallback.py:
(1) nur Cluster ohne release_date werden angefragt,
(2) ein bestehendes Wikidata-Datum wird nie ueberschrieben,
(3) das Ergebnis landet korrekt im kanonischen Record inkl. Quality-Flag.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import internet_archive  # noqa: E402
from pipeline.stage3_normalizer import normalize_record  # noqa: E402
from pipeline.stage4_matcher import run_matcher  # noqa: E402
from pipeline.stage5_enrichment import run_enrichment  # noqa: E402
from pipeline.stage6_conflict_resolution import run_conflict_resolution  # noqa: E402
from pipeline.stage7_quality_check import run_quality_check  # noqa: E402


def fake_search(query, endpoint, timeout=15):
    if "Ohne Datum" in query:
        return {"date": "2019-05-14T00:00:00Z"[:10], "identifier": "fake_item_123", "title": query}
    return None


def main():
    internet_archive.reset_cache()
    internet_archive.search_earliest_date = fake_search  # monkeypatch — kein echtes Netzwerk

    raw = [
        {"_source": "wikidata", "label_raw": "Canon Kamera Mit Datum", "manufacturer_raw": "Canon",
         "image_url": None, "release_date": "2020-01-01", "mount_raw": None},
        {"_source": "wikidata", "label_raw": "Canon Kamera Ohne Datum", "manufacturer_raw": "Canon",
         "image_url": None, "release_date": None, "mount_raw": None},
    ]
    normalized = [normalize_record(r) for r in raw]
    clusters, _ = run_matcher(normalized)
    enriched = run_enrichment(clusters, use_wikimedia_fallback=False, use_internet_archive_fallback=True)
    resolved = run_conflict_resolution(enriched)
    scored, _ = run_quality_check(resolved)

    mit_datum = next(r for r in scored if "Mit Datum" in r["canonical_name"])
    ohne_datum = next(r for r in scored if "Ohne Datum" in r["canonical_name"])

    assert mit_datum["release_date"] == "2020-01-01", \
        "FEHLGESCHLAGEN: bestehendes Wikidata-Datum wurde veraendert"
    assert "datum_via_internet_archive_fallback" not in mit_datum["quality_flags"], \
        "FEHLGESCHLAGEN: Kamera mit Wikidata-Datum faelschlich als Fallback markiert"
    print("OK (1/2): Kamera mit vorhandenem Wikidata-Datum wird nicht angefasst.")

    assert ohne_datum["release_date"] == "2019-05-14", \
        f"FEHLGESCHLAGEN: Fallback-Datum fehlt oder falsch: {ohne_datum.get('release_date')}"
    assert "datum_via_internet_archive_fallback" in ohne_datum["quality_flags"], \
        "FEHLGESCHLAGEN: Fallback-Flag fehlt"
    print("OK (2/2): Kamera ohne Datum bekommt Internet-Archive-Fallback-Datum inkl. Flag.")

    print("\nAlle Checks bestanden.")


if __name__ == "__main__":
    main()
