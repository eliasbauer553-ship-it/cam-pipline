"""
STAGE 2 — RAW IMPORT
Speichert die Discovery-Ergebnisse 1:1 (unverändert) weg, mit Zeitstempel.
Zweck: Nachvollziehbarkeit ("was genau stand am 3. Sept. bei Quelle X?") und
Möglichkeit, spätere Stages neu zu berechnen, ohne erneut zu crawlen.
"""
import json
import logging
from datetime import datetime, timezone

from . import config

log = logging.getLogger("raw_import")


def save_raw(discovery_results: dict[str, list[dict]]) -> dict[str, str]:
    """Schreibt pro Quelle eine Datei data/raw/<quelle>/<ISO-Timestamp>.json
    und zusätzlich data/raw/<quelle>/latest.json (immer der neueste Stand,
    für einfaches Einlesen durch Stage 3)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    written = {}
    for source_name, records in discovery_results.items():
        source_dir = config.RAW_DIR / source_name
        source_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = source_dir / f"{timestamp}.json"
        latest_path = source_dir / "latest.json"

        payload = {
            "source": source_name,
            "fetched_at": timestamp,
            "record_count": len(records),
            "records": records,
        }
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        written[source_name] = str(latest_path)
        log.info("Raw gespeichert: %s (%s Sätze) -> %s", source_name, len(records), latest_path)
    return written


def load_latest_raw(source_name: str) -> list[dict]:
    """Liest den letzten gespeicherten Rohstand einer Quelle zurück
    (z.B. für einen Pipeline-Re-Run ohne neuen Netzwerk-Fetch)."""
    latest_path = config.RAW_DIR / source_name / "latest.json"
    if not latest_path.exists():
        return []
    payload = json.loads(latest_path.read_text())
    return payload.get("records", [])
