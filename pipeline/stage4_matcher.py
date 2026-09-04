"""
STAGE 4 — PRODUCT MATCHER
Gruppiert normalisierte Sätze aus verschiedenen Quellen, die vermutlich
dieselbe Kamera meinen. Da die freien Quellen kein EAN/MPN liefern, matchen
wir über: gleiche normalisierte Marke + Ähnlichkeit des Modellnamens
(Fuzzy-String-Match, Standardbibliothek `difflib` — keine Zusatzabhängigkeit
nötig, bewusst so gewählt, damit die Pipeline ohne pip-Extras lauffähig ist).

Jede Gruppe bekommt eine `match_group_id` und einen `match_confidence`-Wert
(0-100), der in Stage 7 (Quality Check) sichtbar bleibt.
"""
import logging
from difflib import SequenceMatcher

from . import config

log = logging.getLogger("matcher")


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


def run_matcher(normalized_records: list[dict]) -> list[dict]:
    """
    Simpler, transparenter Greedy-Matcher:
    1) nach Marke gruppieren (harte Vorbedingung — wir matchen nie über
       Markengrenzen hinweg, das wäre ein zu hohes Fehlerrisiko),
    2) innerhalb einer Marke: jeden Satz dem best passenden bestehenden
       Cluster zuordnen, wenn die Modellnamen-Ähnlichkeit >= Schwelle liegt,
       sonst neuen Cluster eröffnen.
    """
    by_brand: dict[str, list[dict]] = {}
    for rec in normalized_records:
        key = (rec["entity_type"], rec["brand_normalized"])
        by_brand.setdefault(key, []).append(rec)

    all_clusters: list[dict] = []
    group_counter = 0

    for (entity_type, brand), recs in by_brand.items():
        clusters: list[dict] = []  # {"model_key": str, "members": [rec, ...]}
        for rec in recs:
            model_key = rec["model_normalized"] or rec["canonical_name_candidate"]
            best_cluster, best_score = None, 0.0
            for cluster in clusters:
                score = _similarity(model_key, cluster["model_key"])
                if score > best_score:
                    best_cluster, best_score = cluster, score

            if best_cluster is not None and best_score >= config.FUZZY_MATCH_THRESHOLD:
                best_cluster["members"].append(rec)
                best_cluster["scores"].append(best_score)
            else:
                group_counter += 1
                clusters.append({
                    "match_group_id": f"grp_{group_counter:05d}",
                    "entity_type": entity_type,
                    "model_key": model_key,
                    "members": [rec],
                    "scores": [100.0],  # erstes Mitglied definiert den Cluster
                })
        all_clusters.extend(clusters)

    # match_confidence = niedrigster Ähnlichkeitswert im Cluster (konservativ)
    for cluster in all_clusters:
        cluster["match_confidence"] = round(min(cluster["scores"]), 1)
        del cluster["scores"]

    log.info(
        "Matcher: %s Eingangssätze -> %s Cluster (Kandidaten für kanonische Kameras)",
        len(normalized_records), len(all_clusters),
    )
    return all_clusters
