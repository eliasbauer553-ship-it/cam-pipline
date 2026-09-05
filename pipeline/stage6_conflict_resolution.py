"""
STAGE 6 — CONFLICT RESOLUTION
Für jedes Feld mit mehreren Kandidatenwerten (aus Stage 5) wird EIN
Endwert bestimmt:
  1) Wenn alle Kandidaten (nach Normalisierung) übereinstimmen -> kein
     Konflikt, Wert übernehmen.
  2) Sonst: nach config.FIELD_SOURCE_PRIORITY die höchstpriorisierte Quelle
     gewinnt. Jeder Konflikt wird protokolliert (nichts verschwindet
     stillschweigend — die "verlorenen" Werte landen in `field_conflicts`).
"""
import logging

from . import config

log = logging.getLogger("conflict_resolution")


def _priority_for(field: str) -> list[str]:
    return config.FIELD_SOURCE_PRIORITY.get(field, config.DEFAULT_PRIORITY)


def resolve_field(field: str, candidates: list[dict]) -> tuple[object, list[dict] | None]:
    """Gibt (gewaehlter_wert, konfliktliste_oder_None) zurueck."""
    distinct_values = {c["value"] for c in candidates}
    if len(distinct_values) == 1:
        return candidates[0]["value"], None

    priority = _priority_for(field)
    for preferred_source in priority:
        for c in candidates:
            if c["source"] == preferred_source:
                return c["value"], candidates  # Konflikt vorhanden, aber aufgelöst

    # Keine der priorisierten Quellen war vertreten -> nimm den ersten Kandidaten,
    # aber markiere es deutlich als Notlösung.
    return candidates[0]["value"], candidates


def resolve_record(enriched: dict) -> dict:
    resolved_fields = {}
    conflicts = {}

    for field, candidates in enriched["field_candidates"].items():
        value, conflict_list = resolve_field(field, candidates)
        resolved_fields[field] = value
        if conflict_list is not None:
            conflicts[field] = conflict_list

    return {
        "match_group_id": enriched["match_group_id"],
        "entity_type": enriched["entity_type"],
        "match_confidence": enriched["match_confidence"],
        "sources_present": enriched["sources_present"],
        "raw_member_count": enriched["raw_member_count"],
        **resolved_fields,
        "_conflicts": conflicts,   # leer = keine Widersprüche
    }


def run_conflict_resolution(enriched_records: list[dict]) -> list[dict]:
    resolved = [resolve_record(r) for r in enriched_records]
    n_conflicts = sum(1 for r in resolved if r["_conflicts"])
    log.info(
        "Conflict Resolution: %s Records, davon %s mit mindestens einem Feldkonflikt",
        len(resolved), n_conflicts,
    )
    return resolved
