# LEAP Home Server v1

Lokaler, offline-first Content- und Konfigurationsserver für LEAP-Handhelds. FastAPI normalisiert externe RSS- und Wetterdaten, verarbeitet Bilder und liefert ausschließlich stabile LEAP-Datenmodelle an die Geräte.

## Installation und erster Start

```bash
cp .env.example .env
mkdir -p data/{database,cache,images,logs,distribution}
docker compose up -d --build
```

Die Weboberfläche ist unter **http://localhost:8080/** (im Heimnetz beispielsweise `http://leap.local:8080`) und OpenAPI unter `/docs` erreichbar. Beim Containerstart werden Alembic-Migrationen automatisch ausgeführt. Optional erzeugt `LEAP_SEED_DEMO_DATA=true` drei Geräte und Kategorien.

## Daten und Backup

Alle persistenten Daten liegen im eingebundenen Verzeichnis `./data`: SQLite unter `database/`, Downloads unter `cache/`, verarbeitete Bilder unter `images/` Logs unter `logs/` und versionierte Assets/Firmware unter `distribution/`. Für ein konsistentes Backup den Container kurz stoppen und das gesamte `data/`-Verzeichnis sichern. Es müssen keine Containerdateien editiert werden.

## Bedienung

1. Unter **Geräte** ein Gerät anlegen und Seiten, Interessen sowie Wetterkoordinaten konfigurieren.
2. Unter **News** Kategorien und RSS-/Atom-Feeds anlegen. Ein Feed wird sofort geprüft und importiert.
3. Unter **Assets** Pakete verwalten, Dateien hochladen und Quiz-Fragen bearbeiten oder importieren. Avatar, Chill, Quiz und weitere Inhalte in den Geräteeinstellungen auswählen.
4. Unter **Firmware** eine ESP32-S3 App-Binary hochladen und zunächst als Beta testen; anschließend als Stable freigeben. Den Kanal je Gerät einstellen.
5. Unter **Kommunikation** gemeinsame Nachrichtenvorlagen bearbeiten, aktivieren und über die Position sortieren. **Kommunikation aktiv** steuert pro Gerät Teilnahme und Kommunikationsseite; neue Geräte und bestehende Geräte nach der Migration sind standardmäßig aktiviert. Vorlagen werden als gemeinsames Asset-Paket synchronisiert.
6. Unter **Geräte → Quiz → Mathe-Quiz** Rechenart und Grenze einstellen (z. B. Addition bis 20, Subtraktion bis 100 oder Multiplikation bis 10 für das kleine Einmaleins). Leap erzeugt Aufgaben zufällig und offline mit vier Antworten, Rechenweg und Stellenwerttafel. Auf dem Gerät beginnt die Quizseite mit der Katalogauswahl einschließlich Mathe-Quiz.
7. Im Geräteeditor die 428×142-Vorschau prüfen.

Über **Design** in der Kopfzeile lässt sich zwischen **Hell**, **Dunkel** und
**System** wechseln. Die Auswahl wird pro Browser gespeichert; **System** folgt
dem Farbschema des Betriebssystems. Standard ist **Hell**. Das Design gilt für
die Verwaltungsoberfläche; die Display-Vorschau behält die Gerätefarben.

## Wichtige Geräte-API

- `GET /api/v1/devices/{device_id}/config`
- `GET /api/v1/devices/{device_id}/version` und `/sync`
- `POST /api/v1/devices/{device_id}/checkin`
- `POST /api/v1/devices/{device_id}/sync` (Start-Sync mit Firmware-/Asset-Inventar)
- `POST /api/v1/devices/{device_id}/sync/{sync_id}/events` (Update-Status und Startbestätigung)
- `GET /api/v1/devices/{device_id}/news?limit=20&since=...`
- `GET /api/v1/devices/{device_id}/weather`
- `GET /api/v1/devices/{device_id}/aircraft`
- `GET /api/v1/devices/{device_id}/quiz`
- `GET /api/leap/{device_id}/knowledge/article/{articleRef}`
- `GET /api/leap/{device_id}/knowledge/search?q=wal`
- `GET /api/leap/{device_id}/knowledge/random`
- `GET /api/v1/assets/news/{article_id}/thumb.jpg`

## Entwicklung

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080
pytest
```

Wetter und Flugradar werden alle 15 Minuten einmal je eindeutigem, konfiguriertem Koordinatenpaar aktualisiert und anschließend von allen Geräten an diesem Standort gemeinsam genutzt. Der Radius des Flugradars ist über `LEAP_AIRCRAFT_RADIUS_NM` konfigurierbar. Wissen verwendet je Gerät Klexikon oder MiniKlexikon und hält Artikel sowie verkleinerte Bilder im lokalen Cache. Details stehen in [`docs/api.md`](docs/api.md). V1 implementiert keine Tamagotchi-Logik, Cloud-Synchronisation, Push-Verbindung oder Multiplayer-Logik.

Assets, Datenübernahme, Firmware-Kanäle und das vollständige ESP32-Installationsprotokoll: [`docs/distribution.md`](docs/distribution.md). Die Server-APIs sind implementiert; der Geräteclient muss das dort beschriebene Verfahren in seiner Firmware umsetzen.

## Haustier und Snake (Firmware beta.10)

Die Geräte-Konfiguration bietet im bestehenden Spielebereich `tamagotchi` und
`snake` zusätzlich zu den bisherigen Spielen an. Beide laufen lokal. Bedürfnisse
und Snake-Rekord werden auf dem Gerät gespeichert.

Für das Haustier das gewählte Avatarpaket unter Assets bearbeiten und ein ZIP mit
80×80-PNG-Frames in `idle`, `happy`, `sad`, `hungry`, `tired`, `dirty`, `eating`,
`playing`, `sleeping` hochladen. Je vier Frames, alphabetische Reihenfolge und
400 ms Standarddauer. `data/pet/` und ein äußerer ZIP-Ordner bleiben erhalten.
256×142-PNG-Hintergründe heißen `background_day.png`/`background_night.png` oder
liegen in gleichnamigen Ordnern. Der Import ergänzt die Paketdefinition unter
`tamagotchi.animations` und `tamagotchi.backgrounds.day/night`; Metadaten lassen
sich im vorhandenen Definitionseditor bearbeiten. Die normalen versionierten
Manifeste, Zuweisungen und Sync-Downloads gelten auch für diese Dateien.

Die Geräte-Vorschau zeigt die neuen Spiele und kann die Haustieraktionen mit den
gewählten Paketframes darstellen; Snake ist eine statische Layoutvorschau. Sie
zeigt keinen tatsächlichen Spielstand des Gerätes. Fehlende Assets blockieren
weder Vorschau noch Spiel. Hintergrundwechsel in der Vorschau nutzt Europe/Berlin;
die Firmware nutzt ihre bestehende konfigurierbare Geräte-Zeitzone.


Ab Firmware beta.11 werden beim Quiz alle zugeordneten Kataloge gemeinsam
zufällig gemischt. Die Auswahl und Reihenfolge entstehen auf dem Gerät.
Ältere Avatar-Uploads mit Tier-/Hintergrunddateien, aber ohne Tamagotchi-Metadaten,
werden beim Serverstart bzw. regulären Sync automatisch erkannt und erhalten
einmalig eine ergänzte Paketversion. Kein erneuter Upload nötig; Originaldateien,
ältere Versionen und explizite Definitionen bleiben erhalten. Danach das Gerät
synchronisieren lassen. Die Firmware kann die beschriebenen Ordner auch ohne
neue Metadaten direkt aus bestehenden Manifesten auflösen.
