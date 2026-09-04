"""
STAGE 8 — CANONICAL DATABASE
Schreibt das Endergebnis. Genau DIESE Datei (data/canonical/cameras.json)
lädt die Web-App zur Laufzeit über raw.githubusercontent.com — die Pipeline
und die App sind damit lose gekoppelt: die App weiß nichts von Wikidata,
Matching-Logik etc., sie bekommt nur das fertige, aufgeräumte Ergebnis.
"""
import json
import logging
from datetime import datetime, timezone

from . import config

log = logging.getLogger("canonical_db")


def build_canonical_entry(rec: dict) -> dict:
    """Reduziert/ordnet die internen Felder auf ein stabiles Ausgabeschema.
    Wird bewusst schlank gehalten, damit die Web-App nicht bei jeder
    internen Pipeline-Änderung mit angepasst werden muss."""
    return {
        "id": rec["match_group_id"],
        "brand": rec.get("brand"),
        "model": rec.get("model"),
        "canonical_name": rec.get("canonical_name") or f"{rec.get('brand','')} {rec.get('model','')}".strip(),
        "mount": rec.get("mount"),
        "sensor_width_mm": rec.get("sensor_width_mm"),
        "sensor_height_mm": rec.get("sensor_height_mm"),
        "resolution_w": rec.get("resolution_w"),
        "resolution_h": rec.get("resolution_h"),
        "image_url": rec.get("image_url"),
        "release_date": rec.get("release_date"),
        "sources": rec.get("sources_present"),
        "match_confidence": rec.get("match_confidence"),
        "completeness_score": rec.get("completeness_score"),
        "quality_tier": rec.get("quality_tier"),
        "quality_flags": rec.get("quality_flags"),
    }


def run_canonical_db(scored_records: list[dict], quality_report: dict) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = [build_canonical_entry(r) for r in scored_records]
    entries.sort(key=lambda e: (e["brand"] or "", e["model"] or ""))

    payload = {
        "generated_at": timestamp,
        "pipeline_version": "1.0",
        "sources_used": list(config.SOURCES.keys()),
        "quality_report": quality_report,
        "camera_count": len(entries),
        "cameras": entries,
    }

    out_path = config.CANONICAL_DIR / "cameras.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    report_path = config.CANONICAL_DIR / "quality_report.json"
    report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2))

    log.info("Canonical DB geschrieben: %s (%s Kameras)", out_path, len(entries))
    return payload
