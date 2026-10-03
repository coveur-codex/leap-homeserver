# API

Die vollständige, ausführbare Spezifikation liegt unter `/docs` und `/openapi.json`. Alle Geräteendpunkte beginnen mit `/api/v1/devices/{device_id}`. Deaktivierte oder unbekannte Geräte erhalten HTTP 404.

`config` enthält Identität, Alter, Avatar-Typ (`avatar`), den frei konfigurierbaren Avatar-Namen (`avatarName`), geordnete Seiten, Spiele und Home-Slots. `news` akzeptiert `limit` (1–100) und einen ISO-8601-Parameter `since`. `weather` und `aircraft` liefern providerunabhängige, standortbezogene Modelle und kennzeichnen einen bei Providerfehler weiter verwendeten Cache mit `stale: true`. `quiz` filtert mit `minAge <= device.age`. `checkin` akzeptiert `firmwareVersion`, `battery`, `wifiRssi` und `freeFlash`.

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
Migration `0007` setzt bestehende Geräte auf Addition bis 20 und erhöht ihre
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
