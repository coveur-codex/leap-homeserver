# Architektur

LEAP Home Server ist ein modularer Monolith: FastAPI stellt HTML und REST bereit, SQLAlchemy speichert in SQLite, APScheduler aktualisiert Feeds und räumt alte Artikel auf. Externe Inhalte durchlaufen Services, bevor sie persistiert werden. Geräte sehen niemals Feedparser- oder Open-Meteo-Rohdaten.

## Module

- `core`: Konfiguration, Datenbank, SSRF-Prüfung, Page Registry und 428×142-Layoutkonstanten.
- `services/feeds.py`: Download, Parsing, Unicode-/HTML-Normalisierung und Deduplizierung (GUID, URL, Titel-/Datum-Hash).
- `services/images.py`: validierter Download und JPEG-Ausgabe in 120×80 sowie 142×100.
- `services/weather.py`: austauschbares `WeatherProvider`-Interface, Open-Meteo und stale-fähiger Cache.
- `services/aircraft.py`: kompakte, nach Entfernung sortierte Flugradardaten von ADSB.lol.
- `services/location_data.py`: gemeinsamer 15-Minuten-Cache je Koordinatenpaar; identisch konfigurierte Geräte lösen keine mehrfachen Providerabrufe aus.
- `api`: kleine gerätebezogene JSON-Modelle; `web`: serverseitige Administration.

## Versionierung

Statt nur eines globalen Content-Zählers verwendet V1 `newsVersion`, `weatherVersion`, `aircraftVersion` und `quizVersion`. Das verhindert unnötige Downloads. `/version` bietet aus Kompatibilitätsgründen zusätzlich das Maximum als `contentVersion`; `/sync` liefert die differenzierten Werte. `configVersion` steigt bei jeder Geräteeditor-Speicherung.

SQLite kann dank SQLAlchemy später gegen PostgreSQL ersetzt werden. Ein einzelner Scheduler-Prozess ist für V1 vorgesehen; bei mehreren Web-Workern muss die Scheduler-Rolle separiert werden.

## Versionierte Assets und OTA

Der neue POST-Start-Sync, unveränderliche Paketdownloads, Firmware-Kanäle und Bestätigungsereignisse sind in [distribution.md](distribution.md) beschrieben. Bestehende GET-APIs bleiben für ältere Clients erhalten.
