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
    present = sum(1 for f in config.EXPECTED_FIELDS if rec.get(f))
    completeness = round(present / len(config.EXPECTED_FIELDS), 3)

    flags = []
    if not rec.get("image_url"):
        flags.append("kein_bild")
    if not rec.get("sensor_width_mm"):
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


def run_quality_check(resolved_records: list[dict]) -> tuple[list[dict], dict]:
    scored = [score_record(r) for r in resolved_records]

    report = {
        "total_records": len(scored),
        "by_tier": {
            tier: sum(1 for r in scored if r["quality_tier"] == tier)
            for tier in ("hoch", "mittel", "niedrig")
        },
        "avg_completeness": round(sum(r["completeness_score"] for r in scored) / len(scored), 3) if scored else 0,
        "records_missing_image": sum(1 for r in scored if "kein_bild" in r["quality_flags"]),
        "records_with_conflicts": sum(1 for r in scored if any(f.startswith("feldkonflikte") for f in r["quality_flags"])),
        "records_single_source": sum(1 for r in scored if "nur_eine_quelle" in r["quality_flags"]),
    }
    log.info("Quality Check: %s", report)
    return scored, report
