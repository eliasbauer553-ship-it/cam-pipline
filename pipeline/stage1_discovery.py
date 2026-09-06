"""
STAGE 1 — DISCOVERY
Holt Rohdaten aus jeder in config.SOURCES definierten Quelle.
Jede discover_*()-Funktion gibt eine Liste von dicts zurück — Rohformat
der jeweiligen Quelle, absichtlich NICHT normalisiert (das macht Stage 3).

Warum keine Händler-Feeds (B&H, Idealo, ...)?
Die haben keine offenen Gratis-APIs — Anbindung würde einen bezahlten
Datenfeed-Vertrag voraussetzen. Der Slot dafür ist in config.py vorgesehen
und in enrichment.py bereits als optionaler Merge-Punkt verdrahtet, aber
ohne Zugangsdaten bleibt er inaktiv, statt stillschweigend zu fehlen.
"""
import io
import json
import logging
import tarfile
import time
import urllib.request
import urllib.parse

log = logging.getLogger("discovery")


def _download(url: str, retries: int = 3, timeout: int = 30) -> bytes:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "camera-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001 — bewusst breit, mit Backoff-Retry
            last_err = e
            log.warning("Download-Versuch %s/%s fehlgeschlagen für %s: %s", attempt, retries, url, e)
            time.sleep(2 * attempt)
    raise RuntimeError(f"Download endgültig fehlgeschlagen: {url}") from last_err


def discover_camera_sensor_db(source_cfg: dict) -> list[dict]:
    """Lädt EmberLightVFX/Camera-Sensor-Database, liest data/sensors.json."""
    raw = _download(source_cfg["url"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("data/sensors.json"))
        content = tf.extractfile(member).read()
    payload = json.loads(content)

    records = []
    for vendor, cams in payload.items():
        for cam_name, info in cams.items():
            records.append({
                "_source": "camera_sensor_db",
                "vendor_raw": vendor,
                "model_raw": cam_name,
                "sensor_modes": info.get("sensor dimensions", {}),
            })
    log.info("camera_sensor_db: %s Rohsätze", len(records))
    return records


def discover_lens_db(source_cfg: dict) -> list[dict]:
    """Lädt Luminoid/lens-db, liest data/lenses.json."""
    raw = _download(source_cfg["url"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("data/lenses.json"))
        content = tf.extractfile(member).read()
    payload = json.loads(content)
    for rec in payload:
        rec["_source"] = "lens_db"
    log.info("lens_db: %s Rohsätze", len(payload))
    return payload


WIKIDATA_QUERY = """
SELECT ?item ?itemLabel ?manufacturerLabel ?image ?releaseDate ?mountLabel
       (GROUP_CONCAT(DISTINCT ?altLabel; separator="|") AS ?aliases) WHERE {
  ?item wdt:P31/wdt:P279* wd:Q15328 .          # instance of (subclass of) "camera"
  OPTIONAL { ?item wdt:P176 ?manufacturer. }    # manufacturer
  OPTIONAL { ?item wdt:P18 ?image. }            # image
  OPTIONAL { ?item wdt:P577 ?releaseDate. }     # publication/release date
  OPTIONAL { ?item wdt:P4676 ?mount. }          # lens mount, if modeled
  # Aliase sind der Schlüssel gegen Vokabular-Mismatch zwischen Quellen:
  # Wikidata nennt eine Kamera oft beim Marketingnamen ("Sony Burano"),
  # waehrend andere Quellen den internen Modellcode nutzen ("ILME-FR7") —
  # genau dieser Modellcode steht bei Wikidata meist als Alias hinterlegt.
  OPTIONAL { ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) IN ("en","de")) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,de". }
}
GROUP BY ?item ?itemLabel ?manufacturerLabel ?image ?releaseDate ?mountLabel
LIMIT 2000
"""


def discover_wikidata(source_cfg: dict) -> list[dict]:
    """
    Fragt Wikidata per SPARQL nach allem, was als "camera" (Q15328) oder
    Subklasse davon modelliert ist, inkl. Hersteller, Bild, Erscheinungsdatum.
    Läuft nur mit echtem Internetzugang (z.B. GitHub-Actions-Runner) —
    in einer Sandbox ohne Wikidata-Zugriff schlägt das kontrolliert fehl.
    """
    params = urllib.parse.urlencode({"query": WIKIDATA_QUERY, "format": "json"})
    url = f"{source_cfg['endpoint']}?{params}"
    raw = _download(url, retries=2, timeout=60)
    payload = json.loads(raw)
    bindings = payload.get("results", {}).get("bindings", [])

    records = []
    for b in bindings:
        aliases_str = b.get("aliases", {}).get("value", "")
        records.append({
            "_source": "wikidata",
            "qid": b["item"]["value"].rsplit("/", 1)[-1],
            "label_raw": b.get("itemLabel", {}).get("value"),
            "manufacturer_raw": b.get("manufacturerLabel", {}).get("value"),
            "image_url": b.get("image", {}).get("value"),
            "release_date": b.get("releaseDate", {}).get("value"),
            "mount_raw": b.get("mountLabel", {}).get("value"),
            "aliases_raw": [a for a in aliases_str.split("|") if a] if aliases_str else [],
        })
    log.info("wikidata: %s Rohsätze", len(records))
    return records


DISCOVERERS = {
    "camera_sensor_db": discover_camera_sensor_db,
    "lens_db": discover_lens_db,
    "wikidata": discover_wikidata,
}


def run_discovery(sources: dict) -> dict[str, list[dict]]:
    """Führt alle aktiven Discoverer aus. Ein einzelner Quellenausfall
    bricht die ganze Pipeline NICHT ab — er wird protokolliert und mit
    leerer Liste weitergereicht, damit spätere Stages robust bleiben.
    Quellen vom kind "enrichment_api" (z.B. wikimedia_commons) haben
    bewusst KEINEN eigenen Discovery-Schritt — die werden gezielt in
    Stage 5 (Enrichment) als Fallback angefragt, nicht flächendeckend
    hier vorab gecrawlt. Die werden hier übersprungen, ohne Warnung."""
    results = {}
    for name, cfg in sources.items():
        if cfg.get("kind") == "enrichment_api":
            continue
        fn = DISCOVERERS.get(name)
        if fn is None:
            log.warning("Keine Discoverer-Funktion für Quelle '%s' — übersprungen.", name)
            continue
        try:
            results[name] = fn(cfg)
        except Exception as e:  # noqa: BLE001
            log.error("Discovery für '%s' fehlgeschlagen: %s", name, e)
            results[name] = []
    return results
