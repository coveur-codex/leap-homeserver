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

Unter **System → Datenhaltung → SQLite-Datenbank herunterladen** lässt sich die komplette SQLite-Datenbank als datierte `.db`-Datei sichern. Der Download erstellt mit der SQLite-Backup-Funktion eine konsistente Kopie im laufenden Betrieb, einschließlich bereits bestätigter Änderungen im WAL-Journal. Die Datei kann direkt mit SQLite geöffnet werden; zusätzliche Journaldateien sind nicht erforderlich. Bilder, Cache, Assets und Firmware-Dateien sind darin nicht enthalten.

Alle persistenten Daten liegen im eingebundenen Verzeichnis `./data`: SQLite unter `database/`, Downloads unter `cache/`, verarbeitete Bilder unter `images/` Logs unter `logs/` und versionierte Assets/Firmware unter `distribution/`. Für ein vollständiges Backup inklusive dieser Dateien den Container kurz stoppen und das gesamte `data/`-Verzeichnis sichern. Es müssen keine Containerdateien editiert werden.

## Bedienung

1. Unter **Geräte** ein Gerät anlegen und Seiten, Interessen sowie Wetterkoordinaten konfigurieren.
2. Unter **News** Kategorien und RSS-/Atom-Feeds anlegen. Ein Feed wird sofort geprüft und importiert.
3. Unter **Assets** Pakete verwalten, Dateien hochladen und Quiz-Fragen bearbeiten oder importieren. Avatar, Chill, Quiz und weitere Inhalte in den Geräteeinstellungen auswählen.
4. Jedes Gerät einmal per USB mit der neuen Firmware und seiner LocalConfig starten, damit die Gerätewerte in NVS gespeichert werden. Unter **Firmware** eine universelle ESP32-S3 App-Binary (maximal 4 MiB, ohne LocalConfig.h oder mit `LEAP_PROVISION_DEVICE=0` gebaut) hochladen und zunächst als Beta testen; anschließend als Stable freigeben. Den Kanal je Gerät einstellen. Releases können zurückgezogen, wieder freigegeben oder nach Bestätigung endgültig gelöscht werden. Bereits installierte Firmware bleibt auf den Geräten.
5. Unter **Kommunikation** gemeinsame Nachrichtenvorlagen bearbeiten, aktivieren und über die Position sortieren. **Kommunikation aktiv** steuert pro Gerät Teilnahme und Kommunikationsseite; neue Geräte und bestehende Geräte nach der Migration sind standardmäßig aktiviert. Vorlagen werden als gemeinsames Asset-Paket synchronisiert.
6. Unter **Geräte → Quiz → Mathe-Quiz** Rechenart und Grenze einstellen (z. B. Addition bis 20, Subtraktion bis 100 oder Multiplikation bis 10 für das kleine Einmaleins). Leap erzeugt Aufgaben zufällig und offline mit vier Antworten, Rechenweg und Stellenwerttafel. Auf dem Gerät beginnt die Quizseite mit der Katalogauswahl einschließlich Mathe-Quiz.
7. Im Geräteeditor die 428×142-Vorschau prüfen.
8. Speicherbelegung für Flash (Firmware), LittleFS und PSRAM in der Geräteübersicht oder im Geräteeditor ablesen. Die Werte stammen vom letzten Check-in einer passenden Firmware und sind mit Zeitstempel versehen.

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

Wetter wird alle 15 Minuten, Flugradar standardmäßig alle 30 Sekunden (`LEAP_AIRCRAFT_CACHE_SECONDS`) einmal je eindeutigem, konfiguriertem Koordinatenpaar aktualisiert und anschließend von allen Geräten an diesem Standort gemeinsam genutzt. Der Radius des Flugradars ist über `LEAP_AIRCRAFT_RADIUS_NM` konfigurierbar. Wissen verwendet je Gerät Klexikon oder MiniKlexikon und hält Artikel sowie verkleinerte Bilder im lokalen Cache. Details stehen in [`docs/api.md`](docs/api.md). V1 implementiert keine Tamagotchi-Logik, Cloud-Synchronisation, Push-Verbindung oder Multiplayer-Logik.

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

Vorschau-Regressionsprüfung (Node.js): `node tests/test_aircraft_preview.cjs`.


Chill V1: Weltraum, Lagerfeuer und Schnee werden beim Start als Asset-Pakete
bereitgestellt. Pro Gerät unter „Firmware & Inhalte“ eine Szene auswählen;
Download beim nächsten regulären Sync (Firmware ab 1.0.0-beta.18). Die
Display-Vorschau zeigt die ausgewählte Szene. Details in
[Asset-Verteilung](docs/distribution.md#chill-v1).

Quiz-Tracking: Im Geräteeditor öffnet **Quiz-Ergebnisse und Antwortzeiten** die
Historie mit konkreter Aufgabe, angezeigter Antwortreihenfolge, gewählter/richtiger
Antwort und Antwortzeit. Homeserver zuerst mit `alembic upgrade head` aktualisieren,
danach Firmware ab **1.0.0-beta.20** installieren. Antworten werden bei WLAN-Ausfall
lokal gepuffert und später übertragen; alte Quizantworten sind nicht rückwirkend
verfügbar. Siehe [API-Vertrag](docs/api.md#quiz-antworten-und-antwortzeiten).


Universelle OTA-Firmware lädt Geräte-ID, WLAN, Tasterbelegung und MPU-Ausrichtung
von jedem Gerät aus NVS. Der Server akzeptiert nur Binaries mit dem Build-Marker
`LEAP_UNIVERSAL_NVS_V1` und ohne `LEAP_DEVICE_PROVISIONING_V1`. Der Marker schützt
vor versehentlich verteilten Installations-Builds; er ist keine Signatur.
Vorhandene alte Releases bleiben zum Download erhalten, werden aber nicht mehr
für OTA ausgewählt. Clients ohne `deviceConfigSchema=1` im Start-Sync erhalten
kein Firmware-Angebot, bis sie per USB provisioniert sind. Assets und die
Homeserver-Konfiguration werden weiterhin synchronisiert. Installation und
Hardware-Mapping sind im Firmware-README beschrieben.

### Gemeinsamer Radarausschnitt mit Firmware 1.0.1

Das Regenradar wird vor der Skalierung auf 112×112 Pixel auf einen zentrierten
50×50-km-Mercator-Ausschnitt zugeschnitten (Seitenlänge am Gerätestandort).
Zoom und Zuschnitt berücksichtigen den Breitengrad; Nord bleibt oben. Die API
liefert dafür `mapWidthKm: 50`. Firmware 1.0.1 verwendet dieselbe Projektion für
die Flugzeugpositionen. Der konfigurierbare Flugzeug-Abrufradius bleibt erhalten.
Die neuen Bilder haben einen eigenen Cache-Key; alte Zoom-7-Bilder werden nicht
als Aufnahmen mit dem neuen Maßstab ausgegeben. Beide Repositories aktualisieren.

### Kommunikation über den Homeserver (1.0.2)

Firmware 1.0.2 sendet alle Gruppennachrichten an den Homeserver; Geräte müssen
nicht mehr denselben Funkkanal verwenden. Alle aktivierten Geräte mit freigegebener
Kommunikation rufen die gemeinsame Nachrichtenfolge unabhängig von ihrer aktuellen
Seite etwa alle zwei Sekunden ab. Eingehende Nachrichten werden mit Pling und
Briefsymbol angezeigt; der Besuch der Kommunikationsseite setzt das Symbol zurück.

Der Server prüft aktive Vorlagen und setzt Namen, Text und Symbol selbst ein.
Wiederholungen derselben Sende-ID erzeugen keine doppelten Nachrichten. Die Folge
bleibt bei Serverneustarts erhalten, Nachrichten werden nach sieben Tagen beim
regulären Cleanup entfernt. Migration `0012` wird beim Containerstart automatisch
angewendet. Firmware und Server gemeinsam aktualisieren.

## Dragon Run (Firmware 1.0.4)

Der eingebaute Spielekatalog enthält `dragon_run` / **Dragon Run**. Im Geräteeditor
unter Spiele aktivieren und speichern, anschließend das Gerät synchronisieren.
Bestehende Freigaben werden beim Serverupdate beibehalten; neue Geräte erhalten
Dragon Run in der Standardauswahl. Ältere Firmware ignoriert die unbekannte ID.
Die Gerätevorschau zeigt eine animierte, programmatisch gezeichnete Grafik- und
Steuerungsdemo (Sprung, gehaltenes Ducken, Feuer mit Abklingzeit). Punkte und
Rekorde bleiben lokal auf dem LEAP, die Vorschau verändert keine Spielstände.
Keine neuen Asset-Pakete oder Datenbankmigrationen sind nötig.
