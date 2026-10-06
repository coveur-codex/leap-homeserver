# API

Die vollständige, ausführbare Spezifikation liegt unter `/docs` und `/openapi.json`. Alle Geräteendpunkte beginnen mit `/api/v1/devices/{device_id}`. Deaktivierte oder unbekannte Geräte erhalten HTTP 404.

`config` enthält Identität, Alter, Avatar-Typ (`avatar`), den frei konfigurierbaren Avatar-Namen (`avatarName`), geordnete Seiten, Spiele und Home-Slots. `news` akzeptiert `limit` (1–100) und einen ISO-8601-Parameter `since`. `weather` und `aircraft` liefern providerunabhängige, standortbezogene Modelle und kennzeichnen einen bei Providerfehler weiter verwendeten Cache mit `stale: true`. `quiz` filtert mit `minAge <= device.age`. `checkin` akzeptiert `firmwareVersion`, `battery`, `wifiRssi` und `freeFlash` sowie optional `memory`.

Bildassets sind stabile URLs und senden `Cache-Control: public, max-age=86400, immutable`.

## Wissen

Die Wissensseite muss in der Gerätekonfiguration aktiviert sein. Der Homeserver wählt anhand von `knowledgeSource` automatisch Klexikon oder MiniKlexikon aus; das Gerät kontaktiert die externe Quelle nie selbst. Alle Artikelantworten enthalten `title`, `articleRef`, `text`, ein optionales `image`, `links`, `source`, `originalTitle`, `originalUrl` und einen Lizenzhinweis.

- `GET /api/leap/{device_id}/knowledge/article/{articleRef}` lädt einen Artikel. `articleRef` aus Suchergebnissen oder Links kann unverändert verwendet werden.
- `GET /api/leap/{device_id}/knowledge/search?q=wal&limit=8` sucht in der konfigurierten Quelle. Suchbegriffe müssen 2–80 Zeichen lang sein.
- `GET /api/leap/{device_id}/knowledge/random` liefert einen vollständigen Zufallsartikel für „Entdecke etwas Neues“.
- `GET /api/knowledge/image/{source}/{image_id}.jpg` liefert das bereits verkleinerte, gecachte Artikelbild.

Dieselben drei Geräteendpunkte stehen passend zur bisherigen API auch unter `/api/v1/devices/{device_id}/knowledge/...` bereit. Unbekannte Geräte liefern HTTP 404, deaktiviertes Wissen HTTP 403, ungültige Eingaben HTTP 422 und eine nicht erreichbare Quelle HTTP 503. Artikel und Bilder werden serverseitig geteilt zwischengespeichert. Quellenangabe und `originalUrl` müssen bei einer Darstellung erhalten bleiben; die jeweils am Originalartikel genannten Lizenz- und Urheberbedingungen sind zu beachten.

## Versionierte Assets und OTA

Der neue POST-Start-Sync, unveränderliche Paketdownloads, Firmware-Kanäle und Bestätigungsereignisse sind in [distribution.md](distribution.md) beschrieben. Bestehende GET-APIs bleiben für ältere Clients erhalten.

## Gerätespeicher

Ein Check-in kann die Belegung in Bytes melden:

```json
{
  "memory": {
    "flash": {"used": 2097152, "total": 4194304},
    "littlefs": {"used": 838861, "total": 2097152},
    "psram": {"used": 2097152, "total": 8388608}
  }
}
```

`used` und `total` müssen nichtnegative Werte sein; `used <= total`.
`total: 0` kennzeichnet nicht verfügbaren Speicher. Flash ist die Belegung des
Firmware-Images im aktiven OTA-Slot; LittleFS ist die Inhalts-/Dateisystempartition.
`freeFlash` bleibt der freie LittleFS-Platz für bestehende Clients und Downloads.
Die Geräteübersicht und der Geräteeditor zeigen den Stand des letzten Check-ins
mit Zeitstempel als belegt / gesamt, mit Dezimalkomma und einer Nachkommastelle
(MB = 1.048.576 Bytes). Ältere Geräte ohne `memory` zeigen keine Speicherwerte.
Migration `0008` ergänzt ein optionales JSON-Feld, ohne bestehende Daten zu ändern.


## Regenradar für Geräte

`GET /api/v1/devices/{device_id}/weather/radar` liefert `available`, `stale`
und bei vorhandenem Bild `image`, `updated` (UTC), `source`, `sourceUrl`,
`latitude`, `longitude`. Ohne konfigurierten Standort: 422; unbekanntes oder
inaktives Gerät: 404. Provider-Ausfälle liefern 200 mit `available: false` oder
mit dem letzten Bild und `stale: true`, unabhängig vom normalen Wetterabruf.

RainViewer-Beobachtungen werden auf dem Server auf 112×112 PNG reduziert,
nordorientiert um den Standort zentriert (Zoom 7), mit Standortpunkt und
Orientierungsringen. Das ist ein Niederschlags-Layer ohne Straßenkarte,
keine Vorhersage. Der Server benötigt HTTPS-Zugriff auf
`api.rainviewer.com` und `tilecache.rainviewer.com`. Metadaten/Bilder werden
höchstens alle zehn Minuten pro Standort angefordert; der Geräte-Sync erfolgt
normalerweise alle 15 Minuten. Quellenangabe: RainViewer, https://www.rainviewer.com/.

`image` verweist auf `/api/v1/assets/weather-radar/{sha256}.png` mit fester
Content-Length und unveränderlicher URL. Ein äußerer Vier-Sekunden-Timeout
begrenzt den Providerabruf für den ESP32-HTTP-Timeout. Keine Datenbankmigration.


## Gerätebilder und Flugzeugpositionen (Firmware beta.5)

Die Flugzeugantwort enthält zusätzlich `center: {latitude, longitude}` aus dem
konfigurierten Gerätestandort. `radiusNm` legt den Kartenmaßstab fest; Positionen
und `trackDegrees` der Flugzeuge bleiben unverändert. Die Firmware zeichnet daraus
eine nordorientierte Positionsansicht, keine Straßenkarte oder Live-Verfolgung.

Alle fünf Standard-Avatarpakete enthalten ein transparentes `preview.png` mit
80×80 Pixeln und einen entsprechenden Idle-Frame. Unveränderte originale
SVG-only-Standardpakete werden durch `ensure_packages` idempotent in eine neue,
unveränderliche Paketversion übernommen. Eigene/hochgeladene Versionen werden
nicht überschrieben; alte Versionen bleiben für vorhandene Geräte verfügbar.
Die PNGs sind mit CairoSVG 2.7.1 aus den mitgelieferten SVGs erzeugt; CairoSVG wird
zur Laufzeit nicht benötigt.

Wissensartikel liefern bereits `image` als lokale JPEG-URL aus dem Originalartikel.
Die Firmware zeigt dieses Bild rechts mit erhaltenem Seitenverhältnis; fehlt ein
Bild, bleibt der Text nutzbar. Die Datei wird auch beim späteren Sync nachgeladen,
falls der erste Download fehlgeschlagen ist.

## Mathe-Quiz und Katalogauswahl

`config.mathQuiz` enthält `{ "operation": "add", "limit": 20 }` pro Gerät.
Rechenarten: `add`, `subtract`, `multiply`. Bei Addition/Subtraktion liegen
Operanden und Ergebnis zwischen 0 und `limit` (3–1000). Bei Multiplikation
liegen beide Faktoren zwischen 1 und `limit` (3–20; 10 für das kleine Einmaleins).
Die Firmware erzeugt jede Aufgabe offline; es werden keine Mathe-Fragen gespeichert
oder heruntergeladen. Ohne Einstellung gilt Addition bis 20.

`quiz.catalogs` liefert die aktiven zugewiesenen Kataloge mit `id` und `name`;
jede Zeile in `quiz.questions` enthält zusätzlich `catalogId`. Das bisherige
`questions`-Array bleibt für ältere Firmware erhalten. Neue Firmware zeigt zuerst
die Katalogauswahl und lädt Fragen ausschließlich aus dem gewählten Katalog.
Versionierte Quiz-Pakete verwenden weiterhin `definition.name` und `questionsFile`.
Migration `0008` setzt bestehende Geräte auf Addition bis 20 und erhöht ihre
Konfigurationsversion, damit die Einstellung beim nächsten Sync übertragen wird.

## Flugradar

`GET /api/v1/devices/{device_id}/aircraft` liefert `center` (latitude/longitude),
`updated` (UTC), `ageSeconds` (Alter des Snapshots), `radiusKm` und `aircraft`.
Je Flugzeug kommen `typeName`, `distanceKm`, `altitudeMeters`, `groundSpeedKmh`,
`positionAgeSeconds` (Alter der Position bei Erfassung), `originName` und
`destinationName` hinzu. Die bisherigen Felder `type`, `distanceNm`,
`altitudeFeet`, `groundSpeedKnots`, `trackDegrees` und `radiusNm` bleiben erhalten.
Unbekannte Messwerte und Routen sind `null`; unbekannte Typen heißen
„Unbekannter Flugzeugtyp“. Der lokale Namenskatalog deckt verbreitete Flugzeuge
und Flughäfen ab; unbekannte Flughafencodes werden als Fallback angezeigt.
Start und Ziel werden ausschließlich aus gelieferten `origin`/`destination`
oder `route.origin`/`route.destination` übernommen. ADS-B-Positionen allein
enthalten keine Flugroute; die Standardquelle liefert diese Angaben nicht immer.
Es gibt dafür keine zusätzlichen externen Einzelabfragen.

Der gemeinsame Flugradar-Cache wird standardmäßig alle 30 Sekunden erneuert,
auch bei mehreren Geräten am selben Standort. Bei Providerfehlern bleiben
Beobachtung und ursprünglicher Zeitstempel mit `stale: true` erhalten.
Die Webvorschau holt bei sichtbarer Radarkarte alle 30 Sekunden Daten und
berechnet alle zwei Sekunden die Position entlang eines Großkreises aus
Geschwindigkeit, Flugrichtung und Beobachtungsalter. Entfernung und Radar
verwenden dieselbe geschätzte Position. Nach 120 Sekunden endet die Fortschreibung
und die Position wird als alt gekennzeichnet. Höhe und Tempo bleiben die zuletzt
gemeldeten Werte; geschätzte Positionen werden als solche beschriftet.

## Wetter und nächster Tag

`weather` enthält weiterhin `current` und `today`. Neu sind `timezone`,
`current.isDay` und `tomorrow`. Die beiden Tagesobjekte enthalten `date`
(ISO-Datum am konfigurierten Standort), `weatherCode` (WMO), `min`, `max` und
`precipitationProbability`. Open-Meteo wird für zwei Tage in der lokalen
Standort-Zeitzone abgefragt; „morgen“ ist das zweite Tagesobjekt der Quelle,
keine Berechnung aus dem UTC-Datum des Servers. Wind wird ausdrücklich in
km/h angefordert. Fehlende Vorhersage: `tomorrow: null`; fehlende Einzelwerte:
`null`. Der bestehende Standortcache und die Temperatur-Einheiten C/F bleiben
unverändert. Nach der Aktualisierung eines bestehenden Caches erscheinen die
neuen Felder automatisch.

Die Gerätevorschau zeichnet Wetter-Icons als SVG aus geometrischen Formen und
zeigt aktuelles Wetter sowie eine Morgen-Karte mit Wetterlage, Temperaturspanne,
Datum und Regenwahrscheinlichkeit. Alle WMO-Codes einschließlich Schnee,
Nebel, gefrierendem Niederschlag und Gewitter/Hagel sind berücksichtigt;
klare Nächte erhalten einen Mond. Unbekannte Codes erhalten ein Fragezeichen.

## Kleine Quiz-Antworten für Geräte (Firmware beta.16)

`GET /api/v1/devices/{id}/quiz?metadataOnly=true` liefert Version und alle aktiven
zugewiesenen Kataloge (`id`, `name`), aber `questions: []`. Die Firmware nutzt
dies, sobald versionierte Quiz-Pakete installiert sind; Fragen werden aus den
vollständigen Offline-Paketen gelesen. Der große Katalog wird dadurch nicht
zusätzlich im Content-Snapshot gespeichert.

Ohne installierte Pakete nutzt die Firmware `?limitPerCatalog=200`: eine zufällige,
ohne Wiederholung ausgewählte Stichprobe von höchstens 200 altersgerechten Fragen
je Katalog. Zulässiger Bereich 1–200. Ohne diese Parameter bleibt die bisherige
vollständige Antwort erhalten. Versionierte Paketdateien bleiben vollständig;
die Begrenzung betrifft ausschließlich den Legacy-Content-Endpunkt.

## Quiz-Antworten und Antwortzeiten

`POST /api/v1/devices/{device_id}/quiz-attempts` speichert die endgültige
Antwort als unveränderlichen Snapshot. Beispiel (Indizes sind nullbasiert):

```json
{
  "eventId": "5da91f77d02e442b984fc10781aaa546",
  "kind": "math",
  "quizSetId": "math",
  "quizSetName": "Mathe-Quiz",
  "quizSetVersion": 3,
  "questionId": null,
  "questionIndex": 0,
  "question": "7 + 5 = ?",
  "answers": ["10", "12", "11", "13"],
  "selectedIndex": 2,
  "correctIndex": 1,
  "elapsedMs": 1234,
  "answeredAt": "2026-10-06T12:00:00Z",
  "firmwareVersion": "1.0.0-beta.20",
  "mathOperation": "add",
  "mathLimit": 20
}
```

`answers` enthält genau die angezeigte Reihenfolge; der Server berechnet
`correct` aus den beiden Indizes. `kind` ist `math` oder `catalog`. Bei
versionierten Katalogen ist `quizSetId` die Paket-ID und `quizSetVersion` die
installierte Paketversion. Neue Quiz-Publikationen enthalten Frage-IDs; ältere
Pakete funktionieren mit `questionId: null`, Aufgabentext und Paketversion.
`questionIndex` bezeichnet die Position im auf dem Gerät geladenen Fragenpool.
Beim Mathequiz bezeichnet die Version die Gerätekonfiguration; Rechenart,
Grenze und die konkrete zufällige Aufgabe werden ebenfalls gespeichert.
Aktuelle Zuweisungen oder spätere Katalogänderungen überschreiben keine Antworten.

Die Antwort enthält `{"ok": true, "eventId": "…"}`. Erneute Übertragung derselben
Ereignis-ID und desselben Inhalts ist pro Gerät idempotent. Abweichender Inhalt
unter derselben ID liefert 409. Unbekannte/deaktivierte Geräte erhalten 404,
ungültige Snapshots 422. Auch Antworten aus inzwischen entfernten Quizsets werden
angenommen, damit offline gespeicherte Antworten später übertragen werden können.

`GET /api/v1/devices/{device_id}/quiz-attempts?limit=50&offset=0` liefert
`attempts` (neueste zuerst, maximal 100), einschließlich `correct` und
`receivedAt`, sowie `hasMore`. `answeredAt` ist ohne synchronisierte Geräteuhr
null; Empfangszeit und Gerätezeit werden getrennt angezeigt. `elapsedMs` darf
bei anderen Clients fehlen/null sein. Migration `0009` ergänzt die Ergebnistabelle.

Im Geräteeditor führt **Quiz-Ergebnisse und Antwortzeiten** zur paginierten
Ansicht `/devices/{id}/quiz-results` mit Aufgabe, Antworten, Markierungen,
Antwortzeit und Gesamtzahl richtiger Antworten. Zeitstempel werden in UTC gezeigt.
Firmware ab beta.20 überträgt neue Antworten automatisch; frühere Antworten
wurden auf den Geräten nicht aufgezeichnet und lassen sich nicht nachträglich abrufen.
