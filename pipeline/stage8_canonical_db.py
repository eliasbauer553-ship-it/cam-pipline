"""
STAGE 8 — CANONICAL DATABASE
Schreibt das Endergebnis in ZWEI getrennte Dateien — Kameras und Objektive
werden bewusst nicht gemischt, weil sie unterschiedliche Feldschemata haben
(eine Kamera hat eine Sensorgröße, ein Objektiv hat eine Brennweite; ein
Objektiv in der Kameraliste zu erwarten war der Bug, der die ursprüngliche
Version dieser Pipeline unnötig schlecht aussehen ließ — siehe README).

  data/canonical/cameras.json   <- von der Web-App als Kamera-Referenz genutzt
  data/canonical/lenses.json    <- von der Web-App als Objektiv-Referenz genutzt
"""
import json
import logging
from datetime import datetime, timezone

from . import config
from .stage7_quality_check import aggregate_report

log = logging.getLogger("canonical_db")


def build_canonical_camera(rec: dict) -> dict:
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


def build_canonical_lens(rec: dict) -> dict:
    return {
        "id": rec["match_group_id"],
        "brand": rec.get("brand"),
        "model": rec.get("model"),
        "canonical_name": rec.get("canonical_name") or f"{rec.get('brand','')} {rec.get('model','')}".strip(),
        "mount": rec.get("mount"),
        "focal_min": rec.get("focal_min"),
        "focal_max": rec.get("focal_max"),
        "aperture_max": rec.get("aperture_max"),
        "weight_g": rec.get("weight_g"),
        "price_usd": rec.get("price_usd"),
        "product_url": rec.get("product_url"),
        "image_url": rec.get("image_url"),
        "release_date": rec.get("release_date"),
        "sources": rec.get("sources_present"),
        "match_confidence": rec.get("match_confidence"),
        "completeness_score": rec.get("completeness_score"),
        "quality_tier": rec.get("quality_tier"),
        "quality_flags": rec.get("quality_flags"),
    }


def _write(filename: str, entries: list[dict], entity_label: str, timestamp: str) -> dict:
    entries = sorted(entries, key=lambda e: (e["brand"] or "", e["model"] or ""))
    report = aggregate_report(entries)
    payload = {
        "generated_at": timestamp,
        "pipeline_version": "1.1",
        "entity_type": entity_label,
        "quality_report": report,
        "count": len(entries),
        "items": entries,
    }
    out_path = config.CANONICAL_DIR / filename
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    log.info("Canonical DB geschrieben: %s (%s %s)", out_path, len(entries), entity_label)
    return payload


def run_canonical_db(scored_records: list[dict], quality_report: dict) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cameras = [build_canonical_camera(r) for r in scored_records if r.get("entity_type") == "camera"]
    lenses = [build_canonical_lens(r) for r in scored_records if r.get("entity_type") == "lens"]

    _write("cameras.json", cameras, "camera", timestamp)
    _write("lenses.json", lenses, "lens", timestamp)

    report_path = config.CANONICAL_DIR / "quality_report.json"
    report_path.write_text(json.dumps(quality_report, ensure_ascii=False, indent=2))

    combined = {
        "generated_at": timestamp,
        "pipeline_version": "1.1",
        "sources_used": list(config.SOURCES.keys()),
        "quality_report": quality_report,
        "camera_count": len(cameras),
        "lens_count": len(lenses),
    }
    log.info("Fertig: %s Kameras, %s Objektive", len(cameras), len(lenses))
    return combined
