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
