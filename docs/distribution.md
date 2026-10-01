# Assets, Firmware und Start-Sync (Protokoll v1)

## Verwaltung und Datenübernahme

`Assets` ist die zentrale Inhaltsverwaltung. Unterstützt werden Avatar, Common,
Sound, Wetter, Spiel, Quiz und Chill. Weitere Typen können über die Kategorien-
Registry und die Auswahlregeln in `app/services/distribution.py` ergänzt werden.

Ein Paket erhält eine stabile ID und fortlaufende ganzzahlige Versionen (v1, v2,
…). Datei-Upload, Ersetzen, Löschen, Metadaten- oder Quiz-Änderungen erzeugen eine
neue Version. Mehrere Dateien eines Uploads gehören zu einer gemeinsamen Version.
ZIP-Uploads werden serverseitig entpackt. Alle relativen Dateipfade einschließlich
eines obersten Archivordners bleiben erhalten; der optionale Zielordner wird
vorangestellt. Leere Verzeichnisse benötigen keinen Manifest-Eintrag. ZIPs innerhalb
eines Archivs werden als Dateien übernommen, nicht rekursiv entpackt. Bestehende
Dateien mit gleichem Pfad werden ausschließlich in der neuen Version ersetzt;
andere Dateien bleiben erhalten. Der ganze Upload erzeugt genau eine Version.
Archive und Einzeldateien dürfen je 16 MiB groß sein. Pro Upload sind maximal
1000 Dateien und 64 MiB entpackte Daten erlaubt (je ZIP maximal 1000 Einträge
inklusive Ordner). Pfad-Traversal, absolute Pfade, Links, verschlüsselte Einträge,
doppelte Pfade und beschädigte Archive werden abgelehnt. Bei einem Fehler bleibt
die aktuelle Paketversion unverändert. Wie andere Upload-Blobs bleibt auch das
hochgeladene Archiv intern gespeichert, wird aber nicht an Geräte verteilt.

Ältere Versionen und Dateien bleiben erreichbar. Parallele Bearbeitungen verwenden
`expected` als Versionsprüfung; veraltete Formulare liefern HTTP 409.

Die Migration `0005` ergänzt die Tabellen ohne vorhandene Quiz-Daten zu ersetzen.
Beim Start werden bestehende Quiz-Kataloge einmalig als `quiz-<Katalog-ID>` übernommen.
Frage-IDs, Altersgrenzen, Antworten und Geräteverknüpfungen bleiben erhalten.
`/quiz` leitet zur Asset-Verwaltung um, der alte Import-Endpunkt bleibt kompatibel.
Der Quiz-Editor bietet Fragenformulare und optional einen vollständigen JSON-Editor.
Die erste Antwort ist weiterhin die richtige. `minAge` muss auch der neue
Firmware-Client beim Lesen des Katalogs mit dem Alter aus der Konfiguration filtern.
Die bisherige `/quiz`-Geräte-API behält ihre serverseitige Altersfilterung.

Die fünf vorhandenen SVG-Avatare werden einmalig in den persistenten Paketspeicher
kopiert. Sie sind Ausgangsinhalte für die bestehende Webvorschau; für ein Display,
das kein SVG unterstützt, passende Bitmap-Frames hochladen. Es wird keine
universelle Bildkonvertierung oder zusätzliche Game-Engine eingeführt.

## Dateien und Definitionen

Die Daten liegen unter `$LEAP_DATA_DIR/distribution/blobs/<Hash-Präfix>/<SHA-256>`.
Temporäre Uploads liegen unter `distribution/staging/`. Erst nach vollständigem
Schreiben und fsync wird eine Datei atomar an ihre Hash-Adresse verschoben. Erst
anschließend werden Manifest und aktuelle Versionsnummer gemeinsam in der DB
veröffentlicht. Ein abgebrochener Vorgang kann unreferenzierte Blobs hinterlassen,
aber keine gültige Altversion überschreiben. V1 löscht keine alten Blobs.

Ein Manifest enthält `schemaVersion`, `packageId`, `type`, `version`, `definition`
und `files`. Jeder Dateieintrag enthält relativen `path`, `size`, `sha256` und eine
versionsgebundene relative `url`. Der Server erzeugt außerdem `definition.json`.
Die Paketdefinition enthält ID, Anzeigename, Typ und Version sowie Inhaltsmetadaten.

Avatar-Beispiel für bearbeitbare Metadaten:

```json
{
  "preview": "animations/idle/001.png",
  "minFirmware": "0.9.0",
  "animations": {
    "idle": {
      "frames": ["animations/idle/001.png", "animations/idle/002.png"],
      "frameDurationMs": 120
    }
  }
}
```

Uploads in `animations/<Name>/` ergänzen automatisch die Frame-Liste in
alphabetischer Reihenfolge. Frame-Namen deshalb mit führenden Nullen nummerieren.
Timing kann anschließend im Definitionseditor angepasst werden. Ein Quiz-Paket
enthält `questions.json`, ein Spielpaket nur Grafiken, Sounds, Level und Daten.
Firmware-Abhängigkeiten können mit `minFirmware` angegeben werden; ein neues
Spielprinzip benötigt weiterhin eine passende Firmware-Engine. Die Firmware muss
unterstützte Dateiformate, Engines und verfügbaren Speicher selbst prüfen.

## Automatische Auswahl

Gerätekonfiguration und Binärinhalte sind getrennt:

- genau der konfigurierte Avatar (`dragon` bleibt als Alias für `avatar-dragon` gültig);
- alle Common-Pakete für alle Geräte;
- ausgewählte Chill-, Sound-, Wetter- und Spielinhalte;
- aktivierte Quiz-Kataloge aus den bestehenden Gerätezuordnungen.

Die Auswahl gilt unabhängig von der momentanen Sichtbarkeit der Display-Seite.
Es gibt keine separate manuelle Paketzuordnung und keinen Hintergrund-Push.

## Firmware

`Firmware` akzeptiert ESP32-S3 App-Binaries aus der Arduino IDE, keine Bootloader
oder zusammengeführten Flash-Images. Dateiendung, ESP-Image-Magic und S3-Chip-ID
werden geprüft. Die Firmware prüft zusätzlich das vollständige Image und seine
Partitionstauglichkeit vor der OTA-Aktivierung. Maximalgröße: 16 MiB pro Upload.

Versionen haben das Format `X.Y.Z` oder `X.Y.Z-beta.N`. Versionen sind einmalig;
Binaries werden nie ersetzt. Releases speichern Kanal, Notes, UTC-Uploadzeit,
Größe und SHA-256. Ein Beta-Release kann ohne erneuten Upload als Stable freigegeben
werden. Stable-Geräte erhalten ausschließlich Stable-Releases. Beta-Geräte erhalten
die höchste Version aus beiden Kanälen. Der Vergleich erfolgt numerisch, nicht
nach Uploadzeit; es gibt keine automatischen Downgrades. Unbekannte alte
Versionsformate erhalten kein automatisches OTA-Angebot, bis der Client eine
vergleichbare Version meldet. Der serverseitige Gerätekanal ist maßgeblich, nicht
der optional vom Gerät gemeldete Kanal.

## API-Ablauf

Die bisherigen GET-Endpunkte `/config`, `/sync`, `/version`, `/quiz` sowie `/checkin`
bleiben erhalten. Der neue Start-Sync ist ein POST:

```http
POST /api/v1/devices/leap-lars/sync
Content-Type: application/json

{"firmwareVersion":"0.8.0","firmwareChannel":"stable",
 "installedAssets":{"avatar-dragon":1},"freeFlash":4000000}
```

Antwort: `syncId`, `configVersion`, `configUrl`, `firmwareChannel`, `firmware`
(oder null), `desiredAssets`, `assetUpdates`, `blockedAssets`, `previousAssets`,
`cleanupAllowed: false`, `cleanupAfter: "boot_success"` und Installationsstrategie.
`assetUpdates` enthält Paketversionen, Manifest-URLs und `downloadBytes`.
`firmware` enthält Version, Release-ID, Kanal, Größe, Hash und Binary-URL.

Downloads (HTTP GET):

- `/api/v1/packages/{packageId}/versions/{version}/manifest`
- `/api/v1/packages/{packageId}/versions/{version}/files/{path}`
- `/api/v1/firmware/{releaseId}/binary`

Dateien und Binaries werden über FileResponse gestreamt, mit Content-Length,
Hash-ETag und unveränderlichen URLs. Der Client lädt Einzeldateien, keine ZIPs.
Firmware wird blockweise direkt in die inaktive OTA-Partition geschrieben und
benötigt keine Zwischenkopie in LittleFS.

### Ablauf auf dem ESP32-S3 (im Firmware-Projekt zu implementieren)

1. Aktive Konfiguration und Inventar laden; POST-Sync ausführen. `syncId` und Plan
   dauerhaft speichern. Konfiguration separat über `configUrl` holen und ihre
   `configVersion` mit dem Plan vergleichen; bei Abweichung erneut synchronisieren.
2. Wenn Firmware angeboten wird: `download_started` melden, Binary in die inaktive
   OTA-Partition streamen, Länge und SHA-256 prüfen, ESP-Image validieren. Erst dann
   aktivieren und `firmware_installed` melden. Bei Fehlern bisherige Partition behalten.
3. Nach Neustart Selbsttest durchführen, ESP-IDF-Image als gültig markieren und
   `firmware_confirmed` mit der neuen Version an den gespeicherten Sync melden.
   Bei fehlgeschlagenem Selbsttest OTA-Rollback; danach `rollback` melden.
4. Nach Firmware-Wechsel einen neuen POST-Sync mit dem neuen Firmwarestand starten.
   Dadurch werden eventuell über `minFirmware` blockierte Assets neu bewertet.
5. Für jedes Asset einen separaten Versionsordner anlegen. Ausreichend Platz für
   aktive UND neue Version prüfen; `downloadBytes` umfasst Dateien inklusive
   Definition, aber keine Dateisystem-/Journal-Reserve. Bei Platzmangel abbrechen,
   niemals den aktiven Avatar löschen. Dateien blockweise laden und inkrementell
   hashen. Vor Aktivierung alle Größen, Hashes, Formate und Referenzen prüfen.
6. Aktiven Paketzeiger atomar wechseln, bisherigen Zeiger als Rückfall behalten.
   `asset_installed` melden. Mit dem neuen Inhalt starten und Selbsttest durchführen.
7. `boot_success` mit Firmwareversion und aktivem vollständigen Asset-Inventar
   melden. Erst eine erfolgreiche Antwort mit `cleanupAllowed: true` gibt die
   konkreten alten `{packageId, version}` aus `removeVersions` zur Löschung frei.
   Bei Netzausfall die Altversionen behalten. Niemals den gerade aktiven Ordner
   löschen; Paket-ID allein reicht nicht, immer auch die Version vergleichen.
8. Danach `sync_success` melden. Bei Fehlschlag alte Zeiger wiederherstellen,
   `rollback` oder Fehlerereignis melden und beim nächsten Start erneut versuchen.

Events:

```http
POST /api/v1/devices/leap-lars/sync/{syncId}/events
Content-Type: application/json

{"event":"boot_success","firmwareVersion":"0.9.0",
 "installedAssets":{"avatar-jellyfish":2}}
```

Weitere Ereignisse: `download_started`, `asset_installed` (mit `packageId`, `version`),
`firmware_installed`, `firmware_confirmed` (mit `firmwareVersion`), `sync_success`,
`update_failed`, `checksum_failed`, `download_aborted`, `rollback`.
Optionales `message` beschreibt den Fehler. Beim Rollback kann das tatsächliche
Inventar über `installedAssets` und `firmwareVersion` gemeldet werden.

Der Server bindet Meldungen an Gerät und gespeicherten Plan, lehnt fremde,
überholte und abgeschlossene Syncs ab und verlangt vor erfolgreichem Sync einen
bestätigten Start. Konfigurationsänderungen während des Downloads erzwingen einen
neuen Sync, bevor Aufräumen erlaubt wird. Fehlerereignisse schließen den Versuch
ab. Download- und Installationsmeldungen allein erlauben kein Löschen. Eine
Firmware-Bestätigung ist nach angebotenen OTA-Updates zwingend. Meldungen sind
Geräteberichte, kein Ersatz für lokale Validierung oder kryptografische Attestation.

## Betrieb, Grenzen und Backup

Der vorhandene Docker-Bind-Mount `./data:/data` enthält auch alle neuen Dateien;
Container- und Image-Updates behalten sie. `.dockerignore` verhindert, dass lokale
Daten, Firmware oder Secrets beim Image-Build hineinkopiert werden. Das gesamte
`data/` bei gestopptem Container sichern, einschließlich Datenbank UND distribution.
Migrationen laufen wie bisher beim Containerstart. Kein separater Dienst nötig.
Zeitangaben im Verwaltungsbereich sind ausdrücklich UTC.

Die vorhandene Anwendung arbeitet ohne Geräteauthentifizierung im vertrauenswürdigen
Heimnetz. Die neuen Endpunkte übernehmen dieses Zugriffsmodell. SHA-256 schützt
gegen beschädigte Downloads, nicht gegen einen manipulierten Server oder Transport.
Bei Zugriff außerhalb des Heimnetzes sind ein gesicherter Zugang/TLS und ein
geeignetes Authentifizierungskonzept erforderlich. Hardware-OTA, Signaturprüfung,
Boot-Selbsttests und atomare LittleFS-Zeiger bleiben Aufgaben der Firmware.

## Kommunikation

Unter `/communication` werden die globalen Nachrichtenvorlagen verwaltet (Text,
optionales Symbol, Position, aktiv/inaktiv). Die zehn Startvorlagen stammen aus
`app/defaults/communication-messages.json` und werden nur beim ersten Anlegen des
Pakets übernommen. Danach ist die Datenbank maßgeblich; gelöschte Vorlagen bleiben
auch nach einem Neustart gelöscht. Es gibt keine serverseitigen Chats oder Historien.

Jede gespeicherte Änderung veröffentlicht über die vorhandene Asset-Infrastruktur
eine neue Version von `communication-messages` (Typ `communication`).
`definition.json` verweist mit `messagesFile` auf `messages.json`:

```json
{"schemaVersion":1,"messages":[{"id":"dauerhafte-uuid","text":"Hallo!","symbol":"👋","order":1}]}
```

Nur aktive Vorlagen sind enthalten, sortiert nach `order` und bei Gleichstand nach
`id`. IDs bleiben beim Bearbeiten und Umsortieren erhalten und werden nach dem
Löschen nicht wiederverwendet. Text ist auf 120, Symbol auf 16 Unicode-Zeichen
begrenzt. Ein leeres Paket ist gültig. Bestehende Manifest-URLs, SHA-256-Prüfungen,
Versionierung und Installationsbestätigungen gelten unverändert.

Die Gerätekonfiguration liefert `communicationEnabled` (standardmäßig `true`).
Die Seite `communication` übernimmt ihren `enabled`-Wert aus diesem Schalter;
ihre Position bleibt über die Seiteneinstellungen konfigurierbar. Bei `false`
erscheint sie nicht in der Vorschau und das Paket fehlt in `desiredAssets` beim
normalen `POST /api/v1/devices/{device_id}/sync`. Bereits installierte Daten werden
über die bestehende bestätigte Bereinigung behandelt. Die Firmware muss den
Schalter beim Senden, Empfangen und Anzeigen berücksichtigen, auch solange ein
älteres Paket noch lokal liegt.

Alle aktivierten Geräte nutzen einen gemeinsamen ESP-NOW-Gruppenchat. Transport,
Mesh/Relay und der Umgang mit vorübergehend unterschiedlichen Vorlagenversionen
liegen in der Firmware. Die Vorschau zeigt nur ein lokales Beispiel mit einem
normalen vorhandenen Avatar; das Auswählen einer Vorlage versendet nichts.
