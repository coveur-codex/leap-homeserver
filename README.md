# LEAP Home Server v1

Lokaler, offline-first Content- und Konfigurationsserver für LEAP-Handhelds. FastAPI normalisiert externe RSS- und Wetterdaten, verarbeitet Bilder und liefert ausschließlich stabile LEAP-Datenmodelle an die Geräte.

## Installation und erster Start

```bash
cp .env.example .env
mkdir -p data/{database,cache,images,logs}
docker compose up -d --build
```

Die Weboberfläche ist unter **http://localhost:8080/** (im Heimnetz beispielsweise `http://leap.local:8080`) und OpenAPI unter `/docs` erreichbar. Beim Containerstart werden Alembic-Migrationen automatisch ausgeführt. Optional erzeugt `LEAP_SEED_DEMO_DATA=true` drei Geräte und Kategorien.

## Daten und Backup

Alle persistenten Daten liegen im eingebundenen Verzeichnis `./data`: SQLite unter `database/`, Downloads unter `cache/`, verarbeitete Bilder unter `images/` und Logs unter `logs/`. Für ein konsistentes Backup den Container kurz stoppen und das gesamte `data/`-Verzeichnis sichern. Es müssen keine Containerdateien editiert werden.

## Bedienung

1. Unter **Geräte** ein Gerät anlegen und Seiten, Interessen sowie Wetterkoordinaten konfigurieren.
2. Unter **News** Kategorien und RSS-/Atom-Feeds anlegen. Ein Feed wird sofort geprüft und importiert.
3. Unter **Quiz** einen JSON-Katalog hochladen und Geräten zuordnen.
4. Im Geräteeditor die 428×142-Vorschau prüfen.

Über **Design** in der Kopfzeile lässt sich zwischen **Hell**, **Dunkel** und
**System** wechseln. Die Auswahl wird pro Browser gespeichert; **System** folgt
dem Farbschema des Betriebssystems. Standard ist **Hell**. Das Design gilt für
die Verwaltungsoberfläche; die Display-Vorschau behält die Gerätefarben.

## Wichtige Geräte-API

- `GET /api/v1/devices/{device_id}/config`
- `GET /api/v1/devices/{device_id}/version` und `/sync`
- `POST /api/v1/devices/{device_id}/checkin`
- `GET /api/v1/devices/{device_id}/news?limit=20&since=...`
- `GET /api/v1/devices/{device_id}/weather`
- `GET /api/v1/devices/{device_id}/aircraft`
- `GET /api/v1/devices/{device_id}/quiz`
- `GET /api/v1/assets/news/{article_id}/thumb.jpg`

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080
pytest
```

Wetter und Flugradar werden alle 15 Minuten einmal je eindeutigem, konfiguriertem Koordinatenpaar aktualisiert und anschließend von allen Geräten an diesem Standort gemeinsam genutzt. Der Radius des Flugradars ist über `LEAP_AIRCRAFT_RADIUS_NM` konfigurierbar. V1 implementiert keine Wissensprovider, Tamagotchi-Logik, Cloud-Synchronisation, Push-Verbindung oder Multiplayer-Logik; `knowledge` ist in der Page Registry für V2 vorhanden.
