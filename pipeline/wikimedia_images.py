"""
WIKIMEDIA COMMONS — Bild-Fallback für Enrichment (Stage 5)

Kein eigener Discovery-Durchlauf (siehe config.SOURCES["wikimedia_commons"]:
kind="enrichment_api") — stattdessen wird gezielt PRO KAMERA/OBJEKTIV, das
nach Wikidata immer noch kein Bild hat, eine einzelne Suche gegen die
Commons-API abgesetzt. Das ist bewusst so und nicht als flächendeckender
Crawl, weil:
  1) Commons hat keine strukturierte "gehört zu Produkt X"-Verknüpfung wie
     Wikidatas P18 — nur Volltextsuche über Dateinamen/Beschreibungen.
  2) Ein Crawl aller Kamera-Kategorien wäre um Größenordnungen teurer als
     eine gezielte Suche nur für die Lücken, die Wikidata offen lässt.
"""
import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger("wikimedia_images")

_cache: dict[str, dict | None] = {}  # Prozess-lokaler Cache, verhindert Doppel-Anfragen im selben Lauf


def search_commons_image(query: str, endpoint: str, timeout: int = 15) -> dict | None:
    """
    Sucht auf Wikimedia Commons nach einer Bilddatei zu `query` (z.B.
    "Sony Alpha 7 IV camera") und gibt bei Erfolg
        {"url": <Direktlink zur Bilddatei>, "page_title": <Commons-Dateiname>,
         "license_hint": <kurzer Lizenzhinweis, falls die API ihn liefert>}
    zurück, sonst None. Nutzt die öffentliche MediaWiki-Action-API — kein
    API-Key nötig, siehe https://commons.wikimedia.org/w/api.php .

    gsrnamespace=6 beschränkt die Suche auf den File:-Namensraum (also
    tatsächliche Mediendateien, keine Kategorie-/Artikelseiten).
    """
    if query in _cache:
        return _cache[query]

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"{query} camera OR lens filetype:bitmap",
        "gsrnamespace": "6",
        "gsrlimit": "1",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json",
    }
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "camera-pipeline/1.0 (enrichment fallback)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001 — ein einzelner Lookup darf die Pipeline nie stoppen
        log.warning("Wikimedia-Commons-Suche fehlgeschlagen für %r: %s", query, e)
        _cache[query] = None
        return None

    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        _cache[query] = None
        return None

    # Es wurde gsrlimit=1 angefragt, aber sicherheitshalber das erste Ergebnis nehmen
    first_page = next(iter(pages.values()))
    imageinfo = (first_page.get("imageinfo") or [{}])[0]
    image_url = imageinfo.get("url")
    if not image_url:
        _cache[query] = None
        return None

    license_hint = None
    extmeta = imageinfo.get("extmetadata") or {}
    if "LicenseShortName" in extmeta:
        license_hint = extmeta["LicenseShortName"].get("value")

    result = {
        "url": image_url,
        "page_title": first_page.get("title"),
        "license_hint": license_hint,
    }
    _cache[query] = result
    return result


def reset_cache() -> None:
    """Nur für Tests: Cache zwischen isolierten Testfällen leeren."""
    _cache.clear()


def throttle(seconds: float = 0.2) -> None:
    """Kleine, freundliche Pause zwischen Anfragen — die Commons-API ist
    grundsätzlich großzügig für maßvolle Nutzung, aber ein Rücksicht-Delay
    kostet uns nichts und schont die Infrastruktur eines Wikimedia-Projekts."""
    time.sleep(seconds)
