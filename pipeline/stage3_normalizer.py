"""
STAGE 3 — NORMALIZER
Bringt Marken- und Modellnamen aus allen Quellen auf eine gemeinsame Form,
BEVOR gematcht wird. Beispiel aus der Aufgabenstellung:
  "Sony α7 IV" / "Sony A7 IV" / "ILCE-7M4"  ->  "Sony Alpha 7 IV"

Wichtig: Der Originalname bleibt immer als `raw_name` erhalten — normalisiert
wird nur eine zusätzliche Sicht, nichts wird überschrieben/gelöscht.
"""
import logging
import re

log = logging.getLogger("normalizer")

# Marken-Aliasse: alles was links steht wird auf den kanonischen Namen rechts
# gemappt. Groß-/Kleinschreibung und Sonderzeichen werden vor dem Vergleich
# ignoriert (siehe _norm_key).
BRAND_ALIASES = {
    "sony corporation": "Sony", "sony": "Sony",
    "canon inc": "Canon", "canon": "Canon",
    "nikon corporation": "Nikon", "nikon": "Nikon",
    "panasonic corporation": "Panasonic", "panasonic": "Panasonic", "lumix": "Panasonic",
    "fujifilm corporation": "Fujifilm", "fujifilm": "Fujifilm", "fuji": "Fujifilm", "fujinon": "Fujifilm",
    "blackmagic design": "Blackmagic Design", "blackmagic": "Blackmagic Design",
    "arri": "ARRI", "arnold  richter cine technik": "ARRI",
    "red digital cinema": "RED", "red": "RED",
    "olympus corporation": "Olympus", "olympus": "Olympus",
    "om digital solutions": "OM System", "om system": "OM System",
    "leica camera ag": "Leica", "leica": "Leica",
    "sigma corporation": "Sigma", "sigma": "Sigma",
    "ricoh imaging": "Pentax / Ricoh", "pentax": "Pentax / Ricoh",
    "dji": "DJI", "gopro": "GoPro", "insta360": "Insta360",
    "z cam": "Z CAM", "zcam": "Z CAM", "kinefinity": "Kinefinity",
}

# Modell-Namensbereinigung: Herstellercodes/Marketing-Ballast raus,
# Reihenfolge/Schreibweise vereinheitlichen.
MODEL_CLEAN_RULES: list[tuple[str, str]] = [
    (r"\bILCE-?7M4\b", "Alpha 7 IV"),
    (r"\bILCE-?(\d)(\w*)\b", r"Alpha \1\2"),   # generische Sony-ILCE-Codes
    (r"\bα\s*", "Alpha "),                      # griechisches Alpha -> "Alpha"
    (r"\bA(\d{1,2})\b(?!\w)", r"Alpha \1"),     # bare "A7", "A6400" -> "Alpha 7", "Alpha 6400"
    (r"\s{2,}", " "),
    (r"^\s+|\s+$", ""),
]


def _norm_key(s: str) -> str:
    """Nur für den Alias-Lookup: lowercase, Satzzeichen raus."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def normalize_brand(raw_brand: str) -> str:
    if not raw_brand:
        return "Unbekannt"
    key = _norm_key(raw_brand)
    for alias_key, canonical in BRAND_ALIASES.items():
        if _norm_key(alias_key) == key:
            return canonical
    # Kein Alias bekannt -> Titel-Case des Originals als bester Kompromiss,
    # damit unbekannte neue Marken nicht stillschweigend verschwinden.
    return raw_brand.strip().title()


def normalize_model(raw_model: str, brand_canonical: str) -> str:
    if not raw_model:
        return ""
    name = raw_model.strip()
    for pattern, repl in MODEL_CLEAN_RULES:
        name = re.sub(pattern, repl, name, flags=re.IGNORECASE)
    # Markenname im Modellnamen nicht doppelt führen ("Sony Sony Alpha 7 IV")
    if name.lower().startswith(brand_canonical.lower()):
        name = name[len(brand_canonical):].strip(" -")
    return name.strip()


def canonical_name(brand_canonical: str, model_canonical: str) -> str:
    return f"{brand_canonical} {model_canonical}".strip()


def normalize_record(rec: dict) -> dict:
    """Nimmt EINEN Rohsatz (aus beliebiger Quelle) und ergänzt die
    normalisierten Felder, ohne die Rohfelder zu entfernen."""
    source = rec.get("_source")
    entity_type = "camera"  # Default; lens_db überschreibt unten
    raw_aliases: list[str] = []

    if source == "camera_sensor_db":
        raw_brand = rec.get("vendor_raw", "")
        raw_model = rec.get("model_raw", "")
    elif source == "wikidata":
        raw_brand = rec.get("manufacturer_raw", "") or ""
        raw_model = rec.get("label_raw", "") or ""
        raw_aliases = rec.get("aliases_raw", []) or []
        # Herstellername im Label vorangestellt oft doppelt ("Sony Sony A7")
        if raw_model.lower().startswith(raw_brand.lower()):
            raw_model = raw_model[len(raw_brand):].strip()
    elif source == "lens_db":
        raw_brand = rec.get("brand", "")
        raw_model = rec.get("model", "")
        entity_type = "lens"
    else:
        log.warning("Unbekannte Quelle beim Normalisieren: %s", source)
        raw_brand, raw_model = "", ""

    brand = normalize_brand(raw_brand)
    model = normalize_model(raw_model, brand)
    # Aliase (z.B. Wikidata-Modellcode "ILME-FR7" neben Marketingname
    # "Burano") werden genauso normalisiert wie der Hauptname — sie sind
    # zusätzliche Namens-KANDIDATEN für den Matcher (Stage 4), nicht
    # Ersatz für den Hauptnamen.
    aliases_normalized = sorted({
        normalize_model(a, brand) for a in raw_aliases if a and a.strip()
    } - {model})

    out = dict(rec)  # Original erhalten
    out["entity_type"] = entity_type
    out["brand_normalized"] = brand
    out["model_normalized"] = model
    out["model_aliases_normalized"] = aliases_normalized
    out["canonical_name_candidate"] = canonical_name(brand, model)
    return out


def run_normalizer(raw_by_source: dict[str, list[dict]]) -> list[dict]:
    normalized = []
    for source_name, records in raw_by_source.items():
        for rec in records:
            normalized.append(normalize_record(rec))
    log.info("Normalizer: %s Sätze verarbeitet", len(normalized))
    return normalized
