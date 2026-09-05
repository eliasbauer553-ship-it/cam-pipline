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
import re
from difflib import SequenceMatcher

from . import config

log = logging.getLogger("matcher")


def _char_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


def _token_set_ratio(a: str, b: str) -> float:
    """Wortmengen-Vergleich statt reinem Zeichenvergleich — löst genau das
    Problem, dass eine Quelle Zusatzwörter anhängt ('A7 IV Full Frame
    Mirrorless' vs. 'Alpha 7 IV'). Nachgebaute Kernidee von fuzzywuzzy's
    token_set_ratio, ohne die Zusatzabhängigkeit: gemeinsame Wörter werden
    isoliert und sowohl gegen 'gemeinsam + nur A' als auch 'gemeinsam + nur B'
    verglichen — Zusatzwörter, die nur EINE Seite hat, drücken den Score
    dann nicht mehr künstlich runter."""
    tokens_a = set(re.findall(r"[a-z0-9]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    only_a = tokens_a - tokens_b
    only_b = tokens_b - tokens_a

    sorted_sect = " ".join(sorted(intersection))
    sorted_a = " ".join(sorted(intersection | only_a))
    sorted_b = " ".join(sorted(intersection | only_b))

    r1 = SequenceMatcher(None, sorted_sect, sorted_a).ratio()
    r2 = SequenceMatcher(None, sorted_sect, sorted_b).ratio()
    r3 = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    return max(r1, r2, r3) * 100


def _similarity(a: str, b: str) -> float:
    """Kombiniert beide Metriken (wie rapidfuzz/fuzzywuzzy es tun) — der
    höhere Wert gewinnt, weil die beiden Schwächen komplementär sind:
    char_ratio ist gut bei kurzen, fast identischen Strings; token_set_ratio
    ist robust gegen angehängte/fehlende Zusatzwörter.

    WICHTIG: Ein erkannter Zahlen-/Generationskonflikt (siehe
    _numeric_conflict) deckelt das Ergebnis hart — sonst würden z.B. zwei
    verschiedene Brennweiten mit sonst identischem Namen fälschlich als
    'gleiches Produkt' durchgehen, weil der Rest des Strings übereinstimmt."""
    score = max(_char_ratio(a, b), _token_set_ratio(a, b))
    if _numeric_conflict(a, b):
        score = min(score, 50.0)
    return score


_GENERATION_MARKERS = {"ii", "iii", "iv", "v", "vi", "gen2", "gen3", "mkii", "mkiii"}


def _numeric_conflict(a: str, b: str) -> bool:
    """Erkennt den gefährlichsten Fehlerfall von Text-Ähnlichkeitsmetriken:
    zwei objektiv VERSCHIEDENE Produkte mit fast identischem Namen, die sich
    nur in einer Zahl oder einem Generationskürzel unterscheiden — z.B.
    'Sigma 24-70mm Art' vs. 'Sigma 24-70mm II Art' (unterschiedliche
    Generationen, beide aktuell im Handel) oder 'RF 24-70mm' vs. 'RF 24-105mm'
    (unterschiedliche Brennweite). Sowohl char_ratio als auch token_set_ratio
    bewerten solche Paare fälschlich hoch, weil der Rest des Strings
    identisch ist. Diese Funktion macht daraus ein hartes Stopp-Signal,
    das NICHT von der sonstigen Ähnlichkeit übertrumpft werden darf."""
    digits_a = set(re.findall(r"\d+", a))
    digits_b = set(re.findall(r"\d+", b))
    if digits_a != digits_b:
        return True

    words_a = set(re.findall(r"[a-z]+", a.lower()))
    words_b = set(re.findall(r"[a-z]+", b.lower()))
    gen_a = words_a & _GENERATION_MARKERS
    gen_b = words_b & _GENERATION_MARKERS
    return gen_a != gen_b


def _diagnose_near_misses(clusters_by_key: dict, threshold: float) -> list[dict]:
    """Für jede Marke: welche zwei EINZELNEN (nicht schon gematchten)
    Records lagen am nächsten am Schwellwert, ohne ihn zu erreichen?
    Das macht sichtbar, WARUM z.B. Wikidata- und Camera-Sensor-DB-Einträge
    zur selben Kamera nicht zusammenfanden — ohne dass ich selbst die
    Wikidata-Rohdaten sehen muss. Bewusst nur Cluster mit genau 1 Mitglied
    (sonst wird die Liste too noisy)."""
    near_misses = []
    for (entity_type, brand), clusters in clusters_by_key.items():
        singles = [c for c in clusters if len(c["members"]) == 1]
        for i, a in enumerate(singles):
            for b in singles[i+1:]:
                a_src = a["members"][0]["_source"]
                b_src = b["members"][0]["_source"]
                if a_src == b_src:
                    continue  # uns interessiert hier gezielt Quelle-übergreifend
                score = _similarity(a["model_key"], b["model_key"])
                if score >= threshold - 15 and score < threshold:  # "knapp daneben"-Fenster
                    near_misses.append({
                        "entity_type": entity_type, "brand": brand,
                        "a": a["model_key"], "a_source": a_src,
                        "b": b["model_key"], "b_source": b_src,
                        "similarity": round(score, 1), "threshold": threshold,
                    })
    near_misses.sort(key=lambda x: -x["similarity"])
    return near_misses[:200]  # genug zum Diagnostizieren, ohne die Datei zu sprengen


def run_matcher(normalized_records: list[dict]) -> tuple[list[dict], list[dict]]:
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
    clusters_by_key: dict = {}
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
        clusters_by_key[(entity_type, brand)] = clusters

    # match_confidence = niedrigster Ähnlichkeitswert im Cluster (konservativ)
    for cluster in all_clusters:
        cluster["match_confidence"] = round(min(cluster["scores"]), 1)
        del cluster["scores"]

    near_misses = _diagnose_near_misses(clusters_by_key, config.FUZZY_MATCH_THRESHOLD)

    log.info(
        "Matcher: %s Eingangssätze -> %s Cluster (Kandidaten für kanonische Kameras)",
        len(normalized_records), len(all_clusters),
    )
    if near_misses:
        log.info(
            "Matcher-Diagnose: %s quellenübergreifende Beinahe-Treffer knapp unter der Schwelle "
            "(siehe data/canonical/match_diagnostics.json)", len(near_misses),
        )
    return all_clusters, near_misses
