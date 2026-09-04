# Kamera-Datenbank-Pipeline

Automatisiert die 8-stufige Pipeline (Discovery → Raw Import → Normalizer →
Product Matcher → Enrichment → Conflict Resolution → Quality Check →
Canonical Database) und lässt sie **nachts automatisch per GitHub Actions**
laufen. Das Ergebnis (`data/canonical/cameras.json`) ist eine offene URL,
die eine Web-App live nachladen kann.

## Architektur

```
pipeline/
  config.py                    Quellen, Prioritäten, Schwellwerte — zentral
  stage1_discovery.py          Holt Rohdaten (GitHub-Datensätze + Wikidata)
  stage2_raw_import.py         Speichert Rohdaten unverändert, mit Zeitstempel
  stage3_normalizer.py         "Sony A7 IV" / "ILCE-7M4" -> "Sony Alpha 7 IV"
  stage4_matcher.py            Gruppiert Sätze verschiedener Quellen zur selben Kamera
  stage5_enrichment.py         Sammelt alle Feldwerte pro Kamera-Cluster
  stage6_conflict_resolution.py Entscheidet bei Widersprüchen nach Quellen-Priorität
  stage7_quality_check.py      Vollständigkeits-Score, Flags, Qualitäts-Tier
  stage8_canonical_db.py       Schreibt das finale JSON
  run_pipeline.py              Orchestriert alle 8 Stages
data/
  raw/<quelle>/latest.json     Rohstand pro Quelle (Audit-Trail)
  canonical/cameras.json       ← Kameras — das lädt die Web-App
  canonical/lenses.json        ← Objektive — das lädt der Objektiv-Tab
  canonical/quality_report.json
.github/workflows/
  update-database.yml          Nächtlicher Cron-Job (03:17 UTC) + manueller Trigger
```

## Lokal ausführen

```bash
pip install -r requirements.txt
python -m pipeline.run_pipeline
```

Nur mit bereits heruntergeladenen Rohdaten neu berechnen (kein Netzwerk):
```bash
python -m pipeline.run_pipeline --skip-fetch
```

Nur bestimmte Quellen:
```bash
python -m pipeline.run_pipeline --sources camera_sensor_db lens_db
```

Namens-Normalisierung isoliert testen:
```bash
python tests/test_normalizer_example.py
```

## In GitHub Actions einrichten

1. Dieses Verzeichnis in ein neues GitHub-Repo pushen.
2. Nichts weiter konfigurieren — `permissions: contents: write` im Workflow
   reicht, damit der Bot-Commit mit dem automatisch bereitgestellten
   `GITHUB_TOKEN` funktioniert (Repo-Einstellung *Settings → Actions →
   General → Workflow permissions* muss auf "Read and write" stehen).
3. Der Job läuft ab dann jede Nacht automatisch, oder sofort manuell über
   *Actions → Update Camera Database → Run workflow*.

## Web-App anbinden

Sobald das Repo öffentlich auf GitHub liegt, ist die kanonische Datenbank
unter einer stabilen Rohdaten-URL erreichbar:

```
https://raw.githubusercontent.com/<dein-user>/<dein-repo>/main/data/canonical/cameras.json
```

Die Web-App kann das per `fetch()` beim Laden nachziehen, statt eine
statische Kopie einzubetten — dann wächst sie automatisch mit, sobald die
nächtliche Pipeline neue Kameras findet, ganz ohne dass die App-Datei neu
gebaut werden muss.

## Zwei reale Bugs, die dein erster Produktionslauf aufgedeckt hat

Dein `quality_report` aus einem echten Lauf (817 Records, 0× "hoch",
avg_completeness 0.417) hat zwei Fehler sichtbar gemacht, die in der
Sandbox mit kleineren Testläufen nicht auffielen:

1. **Objektive wurden als Kameras erwartet.** Der Matcher gruppierte nur
   nach Marke, nicht nach Entitätstyp — 454 von 596 Clustern waren in
   Wahrheit Objektive aus `lens_db`, denen dann eine Sensorgröße "fehlte"
   (die sie als Objektiv nie haben können). **Fix:** `entity_type`
   ("camera"/"lens") wird jetzt in Stage 3 gesetzt, der Matcher gruppiert
   danach, und Stage 8 schreibt zwei getrennte Dateien:
   `data/canonical/cameras.json` und `data/canonical/lenses.json`, jede
   mit eigenem, passendem Vollständigkeits-Maßstab (`EXPECTED_FIELDS_CAMERA`
   vs. `EXPECTED_FIELDS_LENS` in `config.py`).
2. **Falsche Feldnamen beim Objektiv-Enrichment.** Stage 5 griff auf
   `fMin`/`fMax`/`aWide` zu — das sind Feldnamen aus einem anderen,
   verwandten Projekt, nicht aus dem tatsächlichen `lens-db`-Schema
   (`focalMin`/`focalMax`/`apertureMaxWide`). Dadurch blieben Brennweite
   und Blende bei praktisch jedem Objektiv leer. **Fix:** korrekte
   Feldnamen, plus `price_usd`/`product_url` neu mit aufgenommen.

Effekt des Doppel-Fixes im selben Testlauf (nur `camera_sensor_db` +
`lens_db`, ohne Wikidata):

| | vorher | nachher |
|---|---|---|
| Objektive Tier "hoch" | 0 / 454 | **454 / 454** |
| Objektive avg. Vollständigkeit | 0,40 | **0,999** |
| Kameras (unverfälscht, ohne Objektiv-Beimischung) | vermischt mit 454 Objektiven | sauber 142 |

Lehre daraus, falls du die Pipeline weiter erweiterst: **jede neue Quelle
sollte in Stage 3 explizit einen `entity_type` setzen**, und Feldnamen
in Stage 5 immer gegen einen echten Rohdatensatz verifizieren
(`data/raw/<quelle>/latest.json` nach einem `--skip-fetch`-Lauf), nicht
aus dem Gedächtnis übernehmen.

## Was diese Pipeline NICHT kann (bewusste Grenzen)

- **Kein EAN/MPN-Abgleich gegen Händler.** B&H, Idealo & Co. haben keine
  offenen Gratis-APIs für Produktabgleich — das bräuchte einen bezahlten
  Datenfeed-Vertrag. Der Matcher arbeitet deshalb mit Marke + Fuzzy-Namens-
  Ähnlichkeit (`difflib`, Schwelle in `config.FUZZY_MATCH_THRESHOLD`).
  Das ist robust genug für die meisten Fälle, aber kein Ersatz für einen
  echten Produktschlüssel — bei sehr ähnlich benannten Modellen einer Marke
  können Cluster falsch zusammen- oder auseinanderfallen. Das
  `match_confidence`-Feld macht sichtbar, wie sicher ein Cluster ist.
- **Wikidata-Abdeckung ist lückenhaft.** Nicht jede Kamera hat einen
  Wikidata-Eintrag, und nicht jeder Eintrag hat ein Bild (P18) hinterlegt.
  Deshalb der `quality_tier`/`quality_flags`-Mechanismus in Stage 7 — die
  Web-App kann Kameras mit `kein_bild` anders behandeln (z. B. generierte
  Illustration statt Foto, wie im Objektiv-Tab der App bereits umgesetzt).
- **Kein Lauf "im Hintergrund" ohne GitHub.** Der Cron-Job läuft auf
  GitHub-Actions-Infrastruktur, nicht auf einem eigenen Server und nicht im
  Browser der Nutzer. Das ist der Standardweg für genau diesen Anwendungsfall
  (geplante Jobs, Ergebnis als Datei im Repo), aber es ist kein
  dauerhaft laufender Prozess im klassischen Sinn — er wacht nachts auf,
  arbeitet ein paar Minuten, schläft wieder ein.
- **In dieser Sandbox ungetestet:** der Wikidata-SPARQL-Aufruf
  (`stage1_discovery.discover_wikidata`) — diese Sandbox hat keinen Zugriff
  auf `query.wikidata.org`. Die Abfrage folgt Standard-SPARQL-Konventionen
  und sollte auf einem normalen GitHub-Actions-Runner (voller
  Internetzugang) funktionieren; beim ersten echten Lauf lohnt sich trotzdem
  ein Blick in den Job-Log.
- **Vollständig getestet in dieser Sandbox:** Discovery + komplette
  Verarbeitungskette gegen die beiden echten, offenen GitHub-Datensätze
  (Camera-Sensor-Database, lens-db) — End-to-End-Lauf erzeugt aktuell
  **142 Kamera-Einträge + 454 Objektiv-Einträge** aus 908 Rohsätzen,
  siehe `tests/`.

## Erweitern

Neue Quelle hinzufügen:
1. Eintrag in `config.SOURCES`.
2. `discover_<name>()`-Funktion in `stage1_discovery.py`, die eine Liste
   von dicts mit `_source` zurückgibt.
3. In `stage3_normalizer.normalize_record()` einen `elif source == "<name>"`-
   Zweig ergänzen, der Marke/Modell aus dem Rohformat extrahiert.
4. Ggf. in `stage5_enrichment.enrich_cluster()` zusätzliche Felder abgreifen.
5. Fertig — Matcher, Conflict Resolution, Quality Check und Canonical DB
   funktionieren automatisch mit, ohne Änderung.
