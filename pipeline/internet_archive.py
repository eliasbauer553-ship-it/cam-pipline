"""
INTERNET ARCHIVE — Erscheinungsdatum-Fallback für Enrichment (Stage 5)

Wie wikimedia_images.py: kein eigener Discovery-Durchlauf (siehe
config.SOURCES["internet_archive"]: kind="enrichment_api") — stattdessen
eine gezielte Suche PRO KAMERA, die nach Wikidata immer noch kein
`release_date` hat, gegen Internet Archives öffentliche Advanced-Search-API
(https://archive.org/advancedsearch.php, kein API-Key nötig).

WICHTIG zur Nutzung: Wir übernehmen ausschließlich das METADATEN-Feld
`date` des frühesten passenden Treffers (z.B. das Datum einer archivierten
Produktankündigung) — niemals den archivierten Volltext/Inhalt selbst.
Das Urheberrecht am archivierten Dokument bleibt unabhängig davon beim
jeweiligen Rechteinhaber; wir zitieren nur "wann existierte das".
"""
import json
import logging
import re
import urllib.parse
import urllib.request

log = logging.getLogger("internet_archive")

_cache: dict[str, dict | None] = {}


def search_earliest_date(query: str, endpoint: str, timeout: int = 15) -> dict | None:
    """
    Sucht in Internet Archives Metadaten-Index nach Items, die zu `query`
    passen (z.B. "Sony Alpha 7 IV"), und gibt das früheste gefundene Datum
    zurück:
        {"date": "2021-10-21", "identifier": <IA-Item-ID>, "title": <Titel>}
    oder None, wenn nichts Passendes gefunden wurde. `rows=5` statt 1, weil
    das erste Suchergebnis nicht zwingend das älteste ist — wir sortieren
    selbst und nehmen das plausibelste (früheste, aber nicht vor 1990 —
    ältere Treffer sind fast immer False Positives bei Digitalkameras).
    """
    if query in _cache:
        return _cache[query]

    params = {
        "q": f'"{query}"',
        "fl[]": "identifier,date,title",
        "rows": "5",
        "sort[]": "date asc",
        "output": "json",
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params, doseq=True)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "camera-pipeline/1.0 (enrichment fallback)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001 — ein einzelner Lookup darf die Pipeline nie stoppen
        log.warning("Internet-Archive-Suche fehlgeschlagen für %r: %s", query, e)
        _cache[query] = None
        return None

    docs = payload.get("response", {}).get("docs", [])
    plausible = [d for d in docs if _looks_plausible(d.get("date"))]
    if not plausible:
        _cache[query] = None
        return None

    best = plausible[0]  # bereits nach Datum aufsteigend sortiert (sort[]=date asc)
    result = {
        "date": _to_iso_date(best["date"]),
        "identifier": best.get("identifier"),
        "title": best.get("title"),
    }
    _cache[query] = result
    return result


def _looks_plausible(date_str: str | None) -> bool:
    """Digitalkameras gibt es erst seit den späten 1980ern — ein Treffer
    von z.B. 1920 ist mit an Sicherheit grenzender Wahrscheinlichkeit ein
    False Positive (Kamera-Marke zufällig im Titel eines alten Dokuments)."""
    if not date_str:
        return False
    m = re.match(r"(\d{4})", date_str)
    if not m:
        return False
    year = int(m.group(1))
    return 1990 <= year <= 2030


def _to_iso_date(date_str: str) -> str:
    """Internet Archive liefert oft volle Timestamps ('2021-10-21T00:00:00Z')
    — wir wollen nur den Datumsteil, konsistent mit Wikidatas Format."""
    return date_str.split("T")[0]


def reset_cache() -> None:
    """Nur für Tests: Cache zwischen isolierten Testfällen leeren."""
    _cache.clear()
