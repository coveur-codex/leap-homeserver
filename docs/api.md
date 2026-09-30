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
