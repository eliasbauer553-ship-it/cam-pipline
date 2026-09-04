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
"""
import logging

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
            # Objektiv-Datensatz taucht nur auf, wenn ein Kamera-Cluster
            # zufällig denselben Marken+Modell-Namen trägt (selten, aber
            # z.B. bei Systemkameras mit gleichnamigem Kit-Objektiv möglich)
            add("mount", ", ".join(member.get("mounts", [])), src)

    return {
        "match_group_id": cluster["match_group_id"],
        "match_confidence": cluster["match_confidence"],
        "sources_present": sorted(sources_present),
        "field_candidates": field_candidates,
        "raw_member_count": len(cluster["members"]),
    }


def run_enrichment(clusters: list[dict]) -> list[dict]:
    enriched = [enrich_cluster(c) for c in clusters]
    log.info("Enrichment: %s Cluster angereichert", len(enriched))
    return enriched
