"""
Orchestriert alle 8 Stages in der im Diagramm vorgegebenen Reihenfolge:

  Discovery -> Raw Import -> Normalizer -> Matcher -> Enrichment
  -> Conflict Resolution -> Quality Check -> Canonical Database

Aufruf lokal:      python -m pipeline.run_pipeline
Aufruf in Actions: siehe .github/workflows/update-database.yml
"""
import argparse
import logging
import sys

from . import config
from .stage1_discovery import run_discovery
from .stage2_raw_import import save_raw, load_latest_raw
from .stage3_normalizer import run_normalizer
from .stage4_matcher import run_matcher
from .stage5_enrichment import run_enrichment
from .stage6_conflict_resolution import run_conflict_resolution
from .stage7_quality_check import run_quality_check
from .stage8_canonical_db import run_canonical_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("pipeline")


def main(skip_fetch: bool = False, sources: list[str] | None = None, no_wikimedia: bool = False) -> dict:
    active_sources = {
        name: cfg for name, cfg in config.SOURCES.items()
        if sources is None or name in sources
    }

    log.info("=== STAGE 1: DISCOVERY ===")
    if skip_fetch:
        log.info("skip_fetch=True -> lese letzten Rohstand statt neuem Netzwerk-Fetch")
        raw_by_source = {name: load_latest_raw(name) for name in active_sources}
    else:
        raw_by_source = run_discovery(active_sources)

    log.info("=== STAGE 2: RAW IMPORT ===")
    if not skip_fetch:
        save_raw(raw_by_source)

    log.info("=== STAGE 3: NORMALIZER ===")
    normalized = run_normalizer(raw_by_source)

    log.info("=== STAGE 4: PRODUCT MATCHER ===")
    clusters, match_diagnostics = run_matcher(normalized)

    log.info("=== STAGE 5: ENRICHMENT ===")
    enriched = run_enrichment(clusters, use_wikimedia_fallback=not no_wikimedia)

    log.info("=== STAGE 6: CONFLICT RESOLUTION ===")
    resolved = run_conflict_resolution(enriched)

    log.info("=== STAGE 7: QUALITY CHECK ===")
    scored, quality_report = run_quality_check(resolved)

    log.info("=== STAGE 8: CANONICAL DATABASE ===")
    payload = run_canonical_db(scored, quality_report, match_diagnostics)

    log.info("=== FERTIG: %s Kameras + %s Objektive in der kanonischen Datenbank ===",
              payload["camera_count"], payload["lens_count"])
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kamera-Datenbank-Pipeline")
    parser.add_argument("--skip-fetch", action="store_true",
                         help="Keine neuen Netzwerk-Abfragen — letzten Rohstand aus data/raw/ wiederverwenden")
    parser.add_argument("--sources", nargs="*", default=None,
                         help="Nur diese Quellen ausführen, z.B. --sources camera_sensor_db lens_db")
    parser.add_argument("--no-wikimedia", action="store_true",
                         help="Wikimedia-Commons-Bild-Fallback deaktivieren (z.B. für netzwerklose Testläufe)")
    args = parser.parse_args()
    main(skip_fetch=args.skip_fetch, sources=args.sources, no_wikimedia=args.no_wikimedia)
