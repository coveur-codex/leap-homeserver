# LEAP Home Server 1.5.1

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

Wetter wird alle 15 Minuten, Flugradar standardmäßig alle 15 Sekunden (`LEAP_AIRCRAFT_CACHE_SECONDS`) einmal je eindeutigem, konfiguriertem Koordinatenpaar aktualisiert und anschließend von allen Geräten an diesem Standort gemeinsam genutzt. Fehlgeschlagene Abrufe werden frühestens nach dem Wetter-Cacheintervall (standardmäßig 15 Minuten) wiederholt; bei HTTP 429 wird eine längere `Retry-After`-Vorgabe der API berücksichtigt. Vorhandene Daten bleiben bei Fehlern als veraltet verfügbar. Der Radius des Flugradars ist über `LEAP_AIRCRAFT_RADIUS_NM` konfigurierbar. Wissen verwendet je Gerät Klexikon oder MiniKlexikon und hält Artikel sowie verkleinerte Bilder im lokalen Cache. Details stehen in [`docs/api.md`](docs/api.md). V1 implementiert keine Tamagotchi-Logik, Cloud-Synchronisation, Push-Verbindung oder Multiplayer-Logik.

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

### Gemeinsamer Radarausschnitt mit Firmware 1.0.8

Das Regenradar wird vor der Skalierung auf 112×112 Pixel auf einen zentrierten
60×60-km-Mercator-Ausschnitt zugeschnitten (Seitenlänge am Gerätestandort).
Zoom und Zuschnitt berücksichtigen den Breitengrad; Nord bleibt oben. Die API
liefert dafür `mapWidthKm: 60`. Firmware 1.0.8 verwendet dieselbe Projektion für
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

## Drachenrennen (Firmware 1.0.5)

Der eingebaute Spielekatalog enthält `dragon_run` / **Drachenrennen**. Im Geräteeditor
unter Spiele aktivieren und speichern, anschließend das Gerät synchronisieren.
Bestehende Freigaben werden beim Serverupdate beibehalten; neue Geräte erhalten
Drachenrennen in der Standardauswahl. Ältere Firmware ignoriert die unbekannte ID.
Die Gerätevorschau zeigt eine animierte, programmatisch gezeichnete Grafik- und
Steuerungsdemo (Sprung, gehaltenes Ducken, Feuer mit Abklingzeit). Punkte und
Rekorde bleiben lokal auf dem LEAP, die Vorschau verändert keine Spielstände.
Keine neuen Asset-Pakete oder Datenbankmigrationen sind nötig.

Die Vorschau übernimmt das ruhigere Starttempo, die längeren Sprünge und den
längeren Feuerstrahl aus Firmware 1.0.5. Die Spiel-ID `dragon_run` bleibt erhalten.

### Einzel-Icons (ab 1.0.3 / Firmware 1.0.6) und aktuelle Radarringe

Der Gerätechat unterstützt zusätzlich 48 feste Kinder-Icons. Firmware 1.0.6 zeigt
sie in einem 3×16-Raster und sendet deren stabile `icon:…`-ID im vorhandenen
`templateId`-Feld. Der Server akzeptiert ausschließlich IDs aus
`app/defaults/communication-icons.json` und speichert ein einzelnes Symbol mit
leerem Text. Berechtigungen, Gruppenverteilung, Historie und idempotente Retries
bleiben identisch zu Textvorlagen. Keine Datenbankmigration oder Änderung des
Vorlagenpakets nötig. Zuerst Homeserver 1.0.3, danach Firmware 1.0.6 installieren.

Regenradarbilder zeigen Ringe bei 10, 20 und 30 km (18/37/55 Pixel Radius), passend zur
60-km-Karte des Flugradars. Die Ringe liegen über dem Regenbild. Ein neuer
Cache-Schlüssel verhindert die Wiederverwendung der bisherigen Ringbilder.


### WebSocket, Gerätefarbe und 60-km-Radare (1.0.4 / Firmware 1.0.8)

Zuerst Homeserver 1.0.4 installieren (Migration 0013), danach Firmware 1.0.8.
Kommunikation nutzt WebSocket-Push, HTTP bleibt für ältere Firmware verfügbar.
Pro Gerät ist unter Allgemein eine Akzentfarbe wählbar (Türkis als Standard).
Regenradar: neuer Cache-Key, 60 × 60 km, Ringe bei 10/20/30 km und N oben mittig.
Firmware 1.0.8 verwendet dieselbe Flugradarprojektion und normal gezeichnete,
unverdickte Überschriften. Protokoll, TLS und Proxy-Anforderungen: [API](docs/api.md).

### Benachrichtigungen (1.0.5 / Firmware 1.0.9)

Zuerst Homeserver 1.0.5 mit Migration 0014 installieren, danach Firmware 1.0.9.
Unter **Geräte → Benachrichtigungstöne** lassen sich Pling (Kommunikation),
Plong (News) und Zisch (Flugzeugnähe) unabhängig ein-/ausschalten. Visuelle
Hinweise bleiben aktiv. Unter **Standort** steht die Höhe in Metern über Meer;
ein leeres Feld entspricht 0 m. Diese gerätespezifische Höhe wird nicht im
geteilten Standort-Cache gespeichert.

Firmware zeigt Hinweise für 5 Sekunden anstelle des Avatars, bündelt neue News
und markiert das passende Modul bis zum Öffnen. Startbestände bleiben still.
Der Absendername und dessen zum Sendezeitpunkt gespeicherte Akzentfarbe gehören
zur Kommunikationsmeldung. News und Flugzeugmeldungen verwenden die eigene Farbe.

Flugradar läuft bei aktivierter Seite auch im Hintergrund und bei Gerätesperre.
Geräteabfrage und Standard-Servercache: 15 Sekunden (`LEAP_AIRCRAFT_CACHE_SECONDS`);
dazwischen wird die Position anhand Kurs und Geschwindigkeit sekündlich geschätzt,
maximal bis 120 Sekunden Beobachtungsalter inklusive `positionAgeSeconds`.
Die Meldung erfolgt beim Eintritt in eine räumliche 3-km-Kugel um den Standort;
erneut erst nach mehr als 3,5 km Entfernung. Ohne bekannte Flugzeughöhe oder mit
veralteten Daten gibt es keine Nähemeldung. Die ADS-B-Barometerhöhe dient als
Näherung; tatsächliche Geräusche und exakte geometrische Höhe werden nicht gemessen.

Firmware 1.0.9 aktualisiert News zusätzlich einmal pro Minute im RAM, damit neue
Titel und Benachrichtigungen zeitnah erscheinen, ohne öfter Flash zu schreiben.

### Nachtruhe (1.0.6 / Firmware 1.0.10)

Unter **Geräte → Benachrichtigungstöne** kann eine Nachtruhe mit Von-/Bis-Uhrzeit
aktiviert werden. Es gilt die lokale Gerätezeit einschließlich Sommerzeit;
Zeitbereiche über Mitternacht sind möglich. Der Beginn ist inklusive, das Ende
exklusive. Nachtruhe ist standardmäßig ausgeschaltet; die vorbelegten Felder
22:00–07:00 werden erst durch Aktivieren wirksam. Gleiche Start-/Endzeiten sind
nicht zulässig. Während der Nachtruhe bleiben Hinweise sichtbar und der
Standby-Seitenwechsel mit Artikel-/Flugzeugauswahl aktiv. Gedämpft werden nur
Benachrichtigungstöne, keine vom Benutzer ausgelösten Spiel-/Bedientöne.

Zuerst Homeserver 1.0.6 (Migration 0015), danach Firmware 1.0.10 installieren.


## 1.1.0: Generative Chill-Musik und LoremFlickr

Unter **Gerät → Chill** steht neben Lagerfeuer, Weltraum und Schnee nun LoremFlickr
zur Auswahl. Das Themenfeld speichert bis zu 80 Zeichen pro Gerät; Standard ist
`nature`, mehrere Begriffe können mit Komma getrennt werden. Die vorhandene
Displayvorschau lädt bei sichtbarer Chill-Karte ein Beispiel zum gespeicherten Thema.
Zufallsbilder sind nicht garantiert kindgerecht. Keywords sind kein Inhaltsfilter.

Vor dem Start `alembic upgrade head` ausführen. Migration 0016 ergänzt ausschließlich
das Thema und hebt die Konfigurationsversion an; vorhandene Inhalte und Auswahlwerte
bleiben erhalten. Das automatisch angelegte Paket `chill-loremflickr` erfordert
Firmware 1.1.0. Stable-/Beta-Auswahl und OTA-Bestätigung verwenden den bisherigen Ablauf.

Der Proxy folgt pro Quelle höchstens sechs HTTPS-Anfragen zu deren bekannten
Bildhosts und begrenzt den Download auf 4 MiB. LoremFlickr erhält bis zu 8 Sekunden,
der Picsum-Fallback bis zu 20 Sekunden. Der Proxy konvertiert höchstens 20 Megapixel
in ein nicht-progressives JPEG (428×142, maximal 128 KiB).
Diese Größe folgt der bestehenden NV3007-Querformatkonfiguration. Pro Gerät bleiben
höchstens zwei Bilddateien erhalten. Gleichzeitige Anfragen werden zusammengefasst,
mit 20 Sekunden Mindestabstand nach Abschluss. Pro Gerät läuft höchstens ein
Hintergrundabruf; Geräteanfragen warten maximal eine Sekunde und erhalten während
der Vorbereitung 503 mit Retry-After. Wiederholungen nutzen denselben Abruf.
Netzwerk-/Bildfehler liefern 503; die Firmware
behält ihr Bild und wiederholt mit Backoff. Die generative Musik benötigt kein Netz.
Siehe [API](docs/api.md) und die [Abnahmehinweise](docs/chill-1.1.0.md).


### Picsum-Fallback bei LoremFlickr-Ausfällen

Bei Timeout, HTTP-Fehler oder unbrauchbaren Bilddaten von LoremFlickr wechselt der
Homeserver automatisch zu **Lorem Picsum** (`picsum.photos`). Nach einem Fehler
wird LoremFlickr fünf Minuten lang ausgesetzt und danach erneut geprüft. Bilder
von Picsum werden genauso zugeschnitten, validiert, gehasht und zwischengespeichert.
Wenn beide Quellen ausfallen, bleibt das letzte Bild auf dem Gerät sichtbar.

**Picsum unterstützt keine Themenwahl.** Das gespeicherte Keyword bleibt erhalten
und wird bei der Rückkehr zu LoremFlickr wieder verwendet. Zufallsbilder beider
Dienste sind nicht garantiert kindgerecht. Die Anpassung benötigt nur ein Update
des Homeservers; Firmware, Chill-Auswahl und Bildübergänge bleiben kompatibel.

## 1.1.1: Mathe-Labor

Die vorhandene Spieleverwaltung bietet `math_lab` als einen Eintrag **Mathe-Labor**
an. Er bündelt auf Firmware 1.1.1 Würfellabor, Zahlenwerkstatt, Würfelarchitekt und
Würfeldetektiv. Im Geräteeditor aktivieren und synchronisieren; anschließend
funktionieren alle Aktivitäten offline und ohne Assets. Bestehende Geräte behalten
ihre Freigaben, neue Geräte erhalten die vorhandene Standardauswahl einschließlich
des Labors. Keine neue Datenbankmigration oder zusätzliche Lernstatistiken.

## 1.1.2: Eigene Chill-Bilder und Nachrichtenavatare

**Gerät → Chill → Eigene Bilder auswählen / hochladen** öffnet die gemeinsame
Bilderbibliothek. Jedes Gerät wählt daraus sein eigenes Album (1–24 Bilder).
Uploads werden ausgerichtet, auf 428×142 zugeschnitten und als kleine JPEGs ohne
EXIF gespeichert; die Originale werden nicht aufbewahrt. Beim Duplizieren eines
Geräts wird die Auswahl unabhängig kopiert, die Bilddateien bleiben dedupliziert.
Nach dem normalen Sync spielt Firmware 1.1.2 die Bilder vollständig offline ab.

Chatnachrichten enthalten jetzt den unveränderlichen Hash eines 48px-Absenderbildes.
Ein automatisch erzeugtes Common-Paket verteilt die kleinen Kommunikationsbilder
aller Avatare an alle Geräte. Die vollständigen fremden Avatarpakete werden nicht
benötigt. Migration 0017 wird beim üblichen Serverstart ausgeführt.
Details: [Anzeige und Bilder 1.1.2](docs/display-photos-chat-1.1.2.md).

## 1.1.3: Zeit-Modul

Das Modul **Zeit** bietet auf Firmware 1.1.4 Timer (1/3/10/60 Minuten
oder eigene Zeit bis 99:59) und eine Stoppuhr mit Zwischenzeiten. Migration
`0018` aktiviert die Seite auf bestehenden Geräten, ohne deren Reihenfolge zu
ändern. Im Geräteeditor lassen sich Seite, Reihenfolge und Timer-Warnton
konfigurieren; die Vorschau verwendet die Geräte-Akzentfarbe. Der Timer läuft
lokal auch auf anderen Seiten und ohne WLAN weiter. Lautstärke, Tonfreigabe und
Nachtruhe gelten. Neustart/Ausschalten verwirft die lokale Zeitmessung.

## Finanzen (1.2.0)

Pro Gerät unter **Seiten → Finanzen** aktivieren und im Abschnitt **Finanzen** Symbole hinzufügen, entfernen und sortieren. Einrichtung, Datenquellen, Tarifgrenzen und Offline-Verhalten: [docs/finance.md](docs/finance.md).

## WLAN und Zahlenzerlegung (1.3.0-beta.1)

Migration 0020 ergänzt je Gerät Serveradresse, vier WLAN-Profile und Zielzahlen
für „Fehlenden Teil finden“ im Mathe-Labor (z. B. `9,10` oder `3-15`, 1–100).
Die Firmware bietet zusätzlich vier lokale WLAN-Profile mit Eingabe am Gerät.
Im Geräteeditor über „WLAN und Server“ / „Zahlenzerlegung“ erreichbar.
Neue Geräte-Route: `GET /api/v1/devices/{id}/network-config`, `Cache-Control: no-store`.
HTTP überträgt Passwörter unverschlüsselt; WLANs im vertrauten Heimnetz vorbereiten.
Die bestehende Geräte-API erhält dadurch keine automatische Zugriffssicherung.
Die optionale kostenlose Yahoo-Quelle für deutsche EUR-Kurse ist in
[Finanzen](docs/finance.md) beschrieben. Keine kostenpflichtigen Dienste erforderlich.

## Kooperatives Snake (1.4.0)

Snake → Multiplayer verbindet 2–4 Geräte automatisch über den Homeserver.
Zehn Sekunden Spielersuche, 3–2–1, dann 120 Sekunden gemeinsame Spielzeit.
Für das neue 53×16-Spielfeld benötigen Firmware und Homeserver Version 1.4.0.
Zum Umstieg zuerst die Firmware, anschließend den Homeserver aktualisieren.
Regeln, Protokoll, Asset-Generierung und Hardware-Abnahme: [docs/snake-multiplayer.md](docs/snake-multiplayer.md).

## Spielestatus (1.4.0)

Der neue Reiter **Spielestatus** zeigt offene Lobbys, Startcountdown, laufende
Partien, verbundene Geräte, Restzeit und Punkte und aktualisiert sich automatisch.
Die gemeinsame Statusschnittstelle unterstützt weitere Spiele ohne Änderungen
am Status-Frontend: [docs/game-status.md](docs/game-status.md).

## OTA-Versionsprüfung (1.4.1)

Neue OTA-Binaries enthalten eine eindeutige LEAP-Dateiversion. Der Homeserver
prüft sie beim Upload gegen die eingetragene Release-Version und vor jedem
Angebot/Download. Falsch beschriftete oder ältere Dateien ohne diese Kennzeichnung
werden nicht mehr automatisch verteilt; die Firmware-Seite zeigt den Grund an.
Diese Kontrolle ergänzt SHA-256 und ESP-Image-Prüfung, sie ist keine Signaturprüfung.

Das GitHub-Buildpaket `leap-esp32s3-1.4.1` enthält `LEAP.ino.bin`, `firmware.json`
(mit Dateiversion, Größe und SHA-256) und `LEAP.ino.bin.sha256`. Für OTA nur die
App-Datei `LEAP.ino.bin` hochladen. Die Release-Version muss zur Datei passen.
Eine unpassende 1.4.0-Veröffentlichung zurückziehen und die neue, korrekt
gekennzeichnete 1.4.1 als neues Release anlegen; bestehende Release-Versionen
werden nicht überschrieben. Gespeicherte Geräte-/WLAN-Konfiguration bleibt erhalten.
Ein universelles Gerät kann die neue Version weiterhin per OTA installieren.

Die Firmware prüft die Dateiversion während des Downloads, vor Boot-Slot-Wechsel
und Journalaktivierung. Eine ausstehende Startbestätigung wird bei Abweichung
zwischen Ziel- und Laufversion verweigert; ein bereits gültiges Fallback bleibt
weiter nutzbar. Bestätigung erfolgt weiterhin nach lokalen Selbsttests auch ohne
WLAN. `SSID not found` betrifft die WLAN-Profilsuche und ist kein Versionsnachweis.

## Home Assistant · Mein Zimmer

Heizung in 1-°C-Schritten (10–30 °C), bis zu zwei Lampen pro Gerät mit An/Aus
und RGB-Farbauswahl: [Einrichtung und Beispiele](docs/home-assistant.md).

## Zimmersteuerung (1.5.0-beta.2)

Temperatur und Lichtfarbe werden direkt mit links/rechts gewählt und erst nach
**einer Sekunde Eingabepause** übertragen. Pro Lampe zeigt eine Farbkachel die
Auswahl; Schwarz bedeutet Aus. Zehn Farben inklusive Orange, Rosa, Türkis und
Hellblau. Zuerst Homeserver 1.5.0-beta.2, dann Firmware 1.5.0-beta.2 installieren.
[Einrichtung und Bedienung](docs/home-assistant.md).

## Bunte Szenenkachel (1.5.1)

Pro Lampe kann im Geräteeditor eine Home-Assistant-Szene (`scene.…`) hinterlegt
werden. Die zusätzliche bunte Kachel startet sie nach einer Sekunde Eingabepause.
Annas Lichterkette erhält `scene.anna_lichterkette_szene` als Startzuordnung.
Zuerst Homeserver 1.5.1 mit Migration 0023, danach Firmware 1.5.1 installieren.
[Einrichtung und Bedienung](docs/home-assistant.md).
