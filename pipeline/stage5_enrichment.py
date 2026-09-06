"""
STAGE 5 — ENRICHMENT
Nimmt jeden Matcher-Cluster (mehrere Rohsätze, vermutlich dieselbe Kamera)
und extrahiert aus jedem Mitglied die Felder, die diese Quelle beitragen
kann. Ergebnis: ein "enriched record" pro Cluster mit ALLEN gefundenen
Werten PRO FELD (noch nicht entschieden — das macht Stage 6).

  field_candidates["weight_g"] = [
      {"value": 658, "source": "wikidata"},
      {"value": 659, "source": "camera_sensor_db"},
  ]

Nach dem regulären Merge läuft optional ein zweiter Schritt: für Cluster,
die IMMER NOCH kein Bild haben, wird eine gezielte Wikimedia-Commons-Suche
als Fallback versucht (siehe wikimedia_images.py) — begrenzt auf
config.WIKIMEDIA_LOOKUP_LIMIT Anfragen pro Lauf.
"""
import logging

from . import config
from . import wikimedia_images
from . import internet_archive

log = logging.getLogger("enrichment")


def _extract_sensor_fields(member: dict) -> dict:
    """camera_sensor_db liefert mehrere Sensor-Modi — wir nehmen den mit der
    größten Fläche als 'nativen' Sensor (siehe Sensor-Datenbank-Feature der
    Web-App, gleiche Logik, damit beide Teile konsistent bleiben)."""
    modes = member.get("sensor_modes") or {}
    if not modes:
        return {}
    best_mode, best_area, best_dims = None, -1, None
    for mode_name, dims in modes.items():
        try:
            w = dims["mm"]["width"]
            h = dims["mm"]["height"]
        except (KeyError, TypeError):
            continue
        if w * h > best_area:
            best_mode, best_area, best_dims = mode_name, w * h, dims
    if best_dims is None:
        return {}
    res = best_dims.get("resolution", {})
    return {
        "sensor_width_mm": best_dims["mm"]["width"],
        "sensor_height_mm": best_dims["mm"]["height"],
        "resolution_w": res.get("width") or None,
        "resolution_h": res.get("height") or None,
        "sensor_mode_name": best_mode,
    }


def enrich_cluster(cluster: dict) -> dict:
    field_candidates: dict[str, list[dict]] = {}

    def add(field, value, source):
        if value is None or value == "":
            return
        field_candidates.setdefault(field, []).append({"value": value, "source": source})

    sources_present = set()
    for member in cluster["members"]:
        src = member["_source"]
        sources_present.add(src)
        add("brand", member["brand_normalized"], src)
        add("model", member["model_normalized"], src)
        add("canonical_name", member["canonical_name_candidate"], src)

        if src == "camera_sensor_db":
            for field, value in _extract_sensor_fields(member).items():
                add(field, value, src)

        elif src == "wikidata":
            add("image_url", member.get("image_url"), src)
            add("release_date", member.get("release_date"), src)
            add("mount", member.get("mount_raw"), src)
            add("manufacturer", member.get("manufacturer_raw"), src)

        elif src == "lens_db":
            add("mount", ", ".join(member.get("mounts", [])), src)
            add("focal_min", member.get("focalMin"), src)
            add("focal_max", member.get("focalMax"), src)
            add("aperture_max", member.get("apertureMaxWide"), src)
            add("weight_g", member.get("weight"), src)
            add("release_date", member.get("year"), src)
            add("price_usd", member.get("priceUSD"), src)
            add("product_url", member.get("productUrl"), src)
            # lens-db führt aktuell keine Produktfotos (kein imageUrl-Feld
            # im Quell-Schema) — bleibt ehrlich leer statt geraten/erfunden.

    return {
        "match_group_id": cluster["match_group_id"],
        "entity_type": cluster["entity_type"],
        "match_confidence": cluster["match_confidence"],
        "sources_present": sorted(sources_present),
        "field_candidates": field_candidates,
        "raw_member_count": len(cluster["members"]),
    }


def run_enrichment(clusters: list[dict], use_wikimedia_fallback: bool = True,
                    use_internet_archive_fallback: bool = True) -> list[dict]:
    enriched = [enrich_cluster(c) for c in clusters]
    log.info("Enrichment: %s Cluster angereichert", len(enriched))

    if use_wikimedia_fallback:
        enriched = _apply_wikimedia_fallback(enriched)
    if use_internet_archive_fallback:
        enriched = _apply_internet_archive_fallback(enriched)
    return enriched


def _apply_internet_archive_fallback(enriched_records: list[dict]) -> list[dict]:
    """Für Cluster ohne release_date: eine gezielte Internet-Archive-Suche
    nach `canonical_name`. Wie beim Wikimedia-Fallback zählt jeder VERSUCH
    gegen das Limit, nicht nur Treffer — sonst könnte ein Lauf mit vielen
    Nicht-Treffern endlos weitersuchen."""
    endpoint = config.SOURCES["internet_archive"]["endpoint"]
    attempts = 0
    found = 0

    for rec in enriched_records:
        if "release_date" in rec["field_candidates"]:
            continue  # schon ein Datum (i.d.R. von Wikidata) — kein Fallback nötig
        if attempts >= config.INTERNET_ARCHIVE_LOOKUP_LIMIT:
            continue

        canonical = rec["field_candidates"].get("canonical_name")
        if not canonical:
            continue
        query = canonical[0]["value"]

        attempts += 1
        result = internet_archive.search_earliest_date(query, endpoint)

        if result:
            found += 1
            rec["field_candidates"].setdefault("release_date", []).append({
                "value": result["date"], "source": "internet_archive",
            })
            rec["sources_present"] = sorted(set(rec["sources_present"]) | {"internet_archive"})

    log.info(
        "Internet-Archive-Fallback: %s Suchanfragen, %s Treffer (Limit: %s)",
        attempts, found, config.INTERNET_ARCHIVE_LOOKUP_LIMIT,
    )
    return enriched_records


def _apply_wikimedia_fallback(enriched_records: list[dict]) -> list[dict]:
    """Für Cluster ohne image_url: eine gezielte Wikimedia-Commons-Suche
    nach `canonical_name`. Bricht nach config.WIKIMEDIA_LOOKUP_LIMIT
    Versuchen ab (nicht Treffern — auch erfolglose Suchen zählen, sonst
    könnte ein Lauf mit vielen Nicht-Treffern trotzdem endlos weitersuchen)."""
    endpoint = config.SOURCES["wikimedia_commons"]["endpoint"]
    attempts = 0
    found = 0

    for rec in enriched_records:
        if "image_url" in rec["field_candidates"]:
            continue  # schon ein Bild (i.d.R. von Wikidata) — kein Fallback nötig
        if attempts >= config.WIKIMEDIA_LOOKUP_LIMIT:
            continue  # Limit erreicht — Rest bleibt fürs naechste Mal offen

        canonical = rec["field_candidates"].get("canonical_name")
        if not canonical:
            continue
        query = canonical[0]["value"]  # noch nicht aufgelöst (Stage 6) — erster Kandidat reicht als Suchbegriff

        attempts += 1
        result = wikimedia_images.search_commons_image(query, endpoint)
        wikimedia_images.throttle()

        if result:
            found += 1
            rec["field_candidates"].setdefault("image_url", []).append({
                "value": result["url"], "source": "wikimedia_commons",
            })
            if result.get("license_hint"):
                rec["field_candidates"].setdefault("image_license_hint", []).append({
                    "value": result["license_hint"], "source": "wikimedia_commons",
                })
            rec["sources_present"] = sorted(set(rec["sources_present"]) | {"wikimedia_commons"})

    log.info(
        "Wikimedia-Commons-Fallback: %s Suchanfragen, %s Treffer (Limit: %s)",
        attempts, found, config.WIKIMEDIA_LOOKUP_LIMIT,
    )
    return enriched_records
