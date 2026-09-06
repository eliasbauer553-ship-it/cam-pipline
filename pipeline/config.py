"""
Zentrale Konfiguration der Pipeline.
Alles, was sich ändern könnte (neue Quelle, neue Prioritäten), gehört hierher —
nicht in die einzelnen Stage-Skripte.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
CANONICAL_DIR = DATA_DIR / "canonical"

for d in (RAW_DIR, NORMALIZED_DIR, CANONICAL_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# QUELLEN (Stage 1 — Discovery)
# Jede Quelle bekommt eine stabile ID; die wird durch die ganze Pipeline
# durchgereicht (Herkunftsnachweis in jedem Record).
# ---------------------------------------------------------------------------
SOURCES = {
    "camera_sensor_db": {
        "kind": "github_tarball",
        "url": "https://codeload.github.com/EmberLightVFX/Camera-Sensor-Database/tar.gz/refs/heads/main",
        "trust_weight": 70,   # Community-gepflegt, sensorbezogen sehr genau
        "license": "siehe Repo (EmberLightVFX/Camera-Sensor-Database)",
    },
    "lens_db": {
        "kind": "github_tarball",
        "url": "https://codeload.github.com/Luminoid/lens-db/tar.gz/refs/heads/main",
        "trust_weight": 70,
        "license": "siehe Repo (Luminoid/lens-db)",
    },
    "wikidata": {
        "kind": "sparql",
        "endpoint": "https://query.wikidata.org/sparql",
        "trust_weight": 60,   # frei editierbar, aber i.d.R. mit Quellenbeleg
        "license": "CC0 (Wikidata)",
    },
    "wikimedia_commons": {
        "kind": "enrichment_api",   # kein eigener Discovery-Durchlauf — siehe stage5_enrichment.py
        "endpoint": "https://commons.wikimedia.org/w/api.php",
        "trust_weight": 40,   # Freitext-Suche, weniger präzise als Wikidatas kuratiertes P18
        "license": "Je nach Datei unterschiedlich (i.d.R. CC BY-SA / CC0 / Public Domain) — Lizenz steht bei jeder Commons-Datei einzeln, wird als 'license_hint' mitgeführt statt pauschal angenommen.",
    },
    "internet_archive": {
        "kind": "enrichment_api",   # kein eigener Discovery-Durchlauf — siehe stage5_enrichment.py
        "endpoint": "https://archive.org/advancedsearch.php",
        "trust_weight": 35,   # Metadaten-Suche über archivierte Presseseiten/Dokumente, nicht kuratiert
        "license": "Wir nutzen NUR Metadaten (frühestes Archivierungs-/Item-Datum) für release_date — keine Volltext-Übernahme archivierter Dokumente, deren Urheberrecht unabhängig vom Internet-Archive-Zugriff beim jeweiligen Rechteinhaber bleibt.",
    },
    # Platzhalter für spätere Erweiterung — bewusst NICHT aktiv, weil sie
    # kostenpflichtige/registrierte API-Zugänge brauchen. Siehe README.
    # "bhphoto_feed": {"kind": "partner_feed", "requires": "API-Key"},
    # "idealo_feed":  {"kind": "partner_feed", "requires": "API-Key"},
}

# ---------------------------------------------------------------------------
# FELD-PRIORITÄT für Konfliktauflösung (Stage 6)
# Bei widersprüchlichen Werten gewinnt die Quelle mit der höchsten Priorität
# FÜR DIESES FELD (nicht pauschal — ein Hersteller-Wikidata-Eintrag ist z.B.
# für "Hersteller" verlässlicher als für "Gewicht").
# ---------------------------------------------------------------------------
FIELD_SOURCE_PRIORITY = {
    "sensor_width_mm":  ["camera_sensor_db", "wikidata"],
    "sensor_height_mm": ["camera_sensor_db", "wikidata"],
    "resolution":       ["camera_sensor_db", "wikidata"],
    "manufacturer":     ["wikidata", "camera_sensor_db", "lens_db"],
    "release_date":     ["wikidata", "internet_archive"],
    "image_url":        ["wikidata", "wikimedia_commons"],
    "mount":            ["lens_db", "wikidata"],
    "weight_g":         ["wikidata"],
}
DEFAULT_PRIORITY = ["wikidata", "camera_sensor_db", "lens_db"]

# Wieviele Wikimedia-Commons-Bildsuchen maximal PRO LAUF durchgeführt werden.
# Das ist eine echte Netzwerk-Anfrage pro fehlendem Bild — ohne Deckel würde
# ein Lauf mit hunderten bildlosen Kameras/Objektiven den 30-Minuten-Timeout
# des GitHub-Actions-Jobs sprengen und die Commons-API unnötig belasten.
# Über mehrere naechtliche Laeufe hinweg fuellt sich die Datenbank so
# schrittweise auf, statt in einem Rutsch alles zu versuchen.
# Ab welchem String-Ähnlichkeitswert (0-100) zwei Namen als "wahrscheinlich
# dieselbe Kamera" gelten (Stage 4 — Matcher).
FUZZY_MATCH_THRESHOLD = 88

# Wieviele Wikimedia-Commons-Bildsuchen maximal PRO LAUF durchgeführt werden.
# Das ist eine echte Netzwerk-Anfrage pro fehlendem Bild — ohne Deckel würde
# ein Lauf mit hunderten bildlosen Kameras/Objektiven den 30-Minuten-Timeout
# des GitHub-Actions-Jobs sprengen und die Commons-API unnötig belasten.
# Über mehrere naechtliche Laeufe hinweg fuellt sich die Datenbank so
# schrittweise auf, statt in einem Rutsch alles zu versuchen.
WIKIMEDIA_LOOKUP_LIMIT = 300

# Analog zu WIKIMEDIA_LOOKUP_LIMIT — Obergrenze für Internet-Archive-
# Metadaten-Anfragen pro Lauf (Erscheinungsdatum-Fallback).
INTERNET_ARCHIVE_LOOKUP_LIMIT = 300

EXPECTED_FIELDS_CAMERA = [
    "brand", "model", "canonical_name", "mount", "sensor_width_mm",
    "sensor_height_mm", "resolution_w", "resolution_h", "image_url",
    "release_date",
]
EXPECTED_FIELDS_LENS = [
    "brand", "model", "canonical_name", "mount", "product_url",
    "release_date", "focal_min", "focal_max", "aperture_max", "weight_g",
]
EXPECTED_FIELDS = EXPECTED_FIELDS_CAMERA  # Rückwärtskompatibilität
