# Architektur

LEAP Home Server ist ein modularer Monolith: FastAPI stellt HTML und REST bereit, SQLAlchemy speichert in SQLite, APScheduler aktualisiert Feeds und räumt alte Artikel auf. Externe Inhalte durchlaufen Services, bevor sie persistiert werden. Geräte sehen niemals Feedparser- oder Open-Meteo-Rohdaten.

## Module

- `core`: Konfiguration, Datenbank, SSRF-Prüfung, Page Registry und 428×142-Layoutkonstanten.
- `services/feeds.py`: Download, Parsing, Unicode-/HTML-Normalisierung und Deduplizierung (GUID, URL, Titel-/Datum-Hash).
- `services/images.py`: validierter Download und JPEG-Ausgabe in 120×80 sowie 142×100.
- `services/weather.py`: austauschbares `WeatherProvider`-Interface, Open-Meteo und stale-fähiger Cache.
- `api`: kleine gerätebezogene JSON-Modelle; `web`: serverseitige Administration.

## Versionierung

Statt nur eines globalen Content-Zählers verwendet V1 `newsVersion`, `weatherVersion` und `quizVersion`. Das verhindert unnötige Downloads. `/version` bietet aus Kompatibilitätsgründen zusätzlich das Maximum als `contentVersion`; `/sync` liefert die differenzierten Werte. `configVersion` steigt bei jeder Geräteeditor-Speicherung.

SQLite kann dank SQLAlchemy später gegen PostgreSQL ersetzt werden. Ein einzelner Scheduler-Prozess ist für V1 vorgesehen; bei mehreren Web-Workern muss die Scheduler-Rolle separiert werden.
