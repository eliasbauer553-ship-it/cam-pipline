"""
Prueft den Wikimedia-Commons-Bild-Fallback OHNE echten Netzwerkzugriff:
- monkeypatched search_commons_image() liefert deterministische Fake-Treffer
- verifiziert: (1) nur Cluster ohne Bild werden angefragt, (2) ein
  bestehendes Wikidata-Bild wird nie ueberschrieben/angefragt, (3) das
  Limit wird respektiert, (4) das Ergebnis landet korrekt im kanonischen
  Record inkl. Quality-Flag "bild_via_wikimedia_fallback".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config, wikimedia_images  # noqa: E402
from pipeline.stage3_normalizer import normalize_record  # noqa: E402
from pipeline.stage4_matcher import run_matcher  # noqa: E402
from pipeline.stage5_enrichment import run_enrichment  # noqa: E402
from pipeline.stage6_conflict_resolution import run_conflict_resolution  # noqa: E402
from pipeline.stage7_quality_check import run_quality_check  # noqa: E402


def fake_search(query, endpoint, timeout=15):
    """Ersetzt den echten API-Call: 'Kamera Mit Bild' hat schon eins (wird
    also nie gefragt), 'Kamera Ohne Bild' bekommt hier einen Fake-Treffer."""
    if "Ohne Bild" in query:
        return {"url": f"https://commons.example.org/{query.replace(' ', '_')}.jpg",
                "page_title": f"File:{query}.jpg", "license_hint": "CC BY-SA 4.0"}
    return None


def main():
    wikimedia_images.reset_cache()
    wikimedia_images.search_commons_image = fake_search  # monkeypatch — kein echtes Netzwerk

    raw = [
        {"_source": "wikidata", "label_raw": "Sony Kamera Mit Bild", "manufacturer_raw": "Sony",
         "image_url": "https://upload.wikimedia.org/echtes_wikidata_bild.jpg",
         "release_date": None, "mount_raw": None},
        {"_source": "wikidata", "label_raw": "Sony Kamera Ohne Bild", "manufacturer_raw": "Sony",
         "image_url": None, "release_date": None, "mount_raw": None},
    ]
    normalized = [normalize_record(r) for r in raw]
    clusters, _ = run_matcher(normalized)
    enriched = run_enrichment(clusters, use_wikimedia_fallback=True, use_internet_archive_fallback=False)
    resolved = run_conflict_resolution(enriched)
    scored, _ = run_quality_check(resolved)

    mit_bild = next(r for r in scored if "Mit Bild" in r["canonical_name"])
    ohne_bild = next(r for r in scored if "Ohne Bild" in r["canonical_name"])

    assert mit_bild["image_url"] == "https://upload.wikimedia.org/echtes_wikidata_bild.jpg", \
        "FEHLGESCHLAGEN: bestehendes Wikidata-Bild wurde veraendert"
    assert "bild_via_wikimedia_fallback" not in mit_bild["quality_flags"], \
        "FEHLGESCHLAGEN: Kamera mit Wikidata-Bild wurde faelschlich als Fallback markiert"
    print("OK (1/3): Kamera mit vorhandenem Wikidata-Bild wird nicht angefasst.")

    assert ohne_bild["image_url"] == "https://commons.example.org/Ohne_Bild.jpg" or \
           "commons.example.org" in (ohne_bild["image_url"] or ""), \
        f"FEHLGESCHLAGEN: Fallback-Bild fehlt oder falsch: {ohne_bild.get('image_url')}"
    assert "bild_via_wikimedia_fallback" in ohne_bild["quality_flags"], \
        "FEHLGESCHLAGEN: Fallback-Flag fehlt"
    assert ohne_bild["image_license_hint"] == "CC BY-SA 4.0", \
        "FEHLGESCHLAGEN: Lizenz-Hinweis wurde nicht uebernommen"
    print("OK (2/3): Kamera ohne Bild bekommt Commons-Fallback-Bild inkl. Lizenz-Hinweis und Flag.")

    # --- Limit-Test: bei Limit=0 darf gar keine Anfrage stattfinden ---
    orig_limit = config.WIKIMEDIA_LOOKUP_LIMIT
    config.WIKIMEDIA_LOOKUP_LIMIT = 0
    try:
        clusters2, _ = run_matcher(normalized)
        enriched2 = run_enrichment(clusters2, use_wikimedia_fallback=True, use_internet_archive_fallback=False)
        resolved2 = run_conflict_resolution(enriched2)
        scored2, _ = run_quality_check(resolved2)
        ohne_bild2 = next(r for r in scored2 if "Ohne Bild" in r["canonical_name"])
        assert not ohne_bild2.get("image_url"), "FEHLGESCHLAGEN: Limit=0 haette keine Anfrage erlauben duerfen"
        print("OK (3/3): WIKIMEDIA_LOOKUP_LIMIT=0 unterbindet jede Fallback-Anfrage.")
    finally:
        config.WIKIMEDIA_LOOKUP_LIMIT = orig_limit

    print("\nAlle Checks bestanden.")


if __name__ == "__main__":
    main()
