"""
STAGE 7 — QUALITY CHECK
Bewertet jeden aufgelösten Record, BEVOR er in die kanonische Datenbank
übernommen wird:
  - completeness_score: Anteil der in config.EXPECTED_FIELDS erwarteten
    Felder, die tatsächlich einen Wert haben (0.0–1.0).
  - flags: Liste konkreter Probleme (fehlende Kernfelder, ungelöste
    Konflikte, niedrige Match-Confidence).
  - quality_tier: "hoch" / "mittel" / "niedrig" — grobe Einordnung, die die
    Web-App nutzen kann, um z.B. Karten mit "niedrig" nur in der reinen
    Referenztabelle statt als Foto-Karte zu zeigen.
"""
import logging

from . import config

log = logging.getLogger("quality_check")


def score_record(rec: dict) -> dict:
    is_lens = rec.get("entity_type") == "lens"
    expected = config.EXPECTED_FIELDS_LENS if is_lens else config.EXPECTED_FIELDS_CAMERA
    present = sum(1 for f in expected if rec.get(f))
    completeness = round(present / len(expected), 3)

    flags = []
    if not rec.get("image_url"):
        flags.append("kein_bild")
    elif rec.get("_field_sources", {}).get("image_url") == "wikimedia_commons":
        flags.append("bild_via_wikimedia_fallback")  # Freitext-Suchtreffer, nicht Wikidatas kuratiertes P18
    if rec.get("_field_sources", {}).get("release_date") == "internet_archive":
        flags.append("datum_via_internet_archive_fallback")
    if not is_lens and not rec.get("sensor_width_mm"):
        flags.append("keine_sensorgroesse")
    if rec.get("match_confidence", 100) < config.FUZZY_MATCH_THRESHOLD:
        flags.append("unsichere_zuordnung")
    if rec.get("_conflicts"):
        flags.append(f"feldkonflikte:{','.join(rec['_conflicts'].keys())}")
    if rec.get("raw_member_count", 0) == 1:
        flags.append("nur_eine_quelle")

    if completeness >= 0.8 and "unsichere_zuordnung" not in flags:
        tier = "hoch"
    elif completeness >= 0.4:
        tier = "mittel"
    else:
        tier = "niedrig"

    out = dict(rec)
    out["completeness_score"] = completeness
    out["quality_flags"] = flags
    out["quality_tier"] = tier
    return out


def aggregate_report(scored: list[dict]) -> dict:
    """Fasst eine Liste bereits gescorter Records zu einem Report zusammen.
    Wiederverwendet in Stage 8, um pro Ausgabedatei (Kameras/Objektive)
    einen eigenen, ehrlichen Report statt eines vermischten zu erzeugen."""
    if not scored:
        return {
            "total_records": 0, "by_tier": {"hoch": 0, "mittel": 0, "niedrig": 0},
            "avg_completeness": 0, "records_missing_image": 0,
            "records_with_conflicts": 0, "records_single_source": 0,
        }
    return {
        "total_records": len(scored),
        "by_tier": {
            tier: sum(1 for r in scored if r["quality_tier"] == tier)
            for tier in ("hoch", "mittel", "niedrig")
        },
        "avg_completeness": round(sum(r["completeness_score"] for r in scored) / len(scored), 3),
        "records_missing_image": sum(1 for r in scored if "kein_bild" in r["quality_flags"]),
        "records_with_conflicts": sum(1 for r in scored if any(f.startswith("feldkonflikte") for f in r["quality_flags"])),
        "records_single_source": sum(1 for r in scored if "nur_eine_quelle" in r["quality_flags"]),
    }


def run_quality_check(resolved_records: list[dict]) -> tuple[list[dict], dict]:
    scored = [score_record(r) for r in resolved_records]
    report = aggregate_report(scored)
    report["by_entity_type"] = {
        "camera": aggregate_report([r for r in scored if r.get("entity_type") == "camera"]),
        "lens": aggregate_report([r for r in scored if r.get("entity_type") == "lens"]),
    }
    log.info("Quality Check (gesamt): %s", {k: v for k, v in report.items() if k != "by_entity_type"})
    log.info("Quality Check (Kameras): %s", report["by_entity_type"]["camera"])
    log.info("Quality Check (Objektive): %s", report["by_entity_type"]["lens"])
    return scored, report
