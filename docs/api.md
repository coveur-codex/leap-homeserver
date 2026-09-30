# API

Die vollständige, ausführbare Spezifikation liegt unter `/docs` und `/openapi.json`. Alle Geräteendpunkte beginnen mit `/api/v1/devices/{device_id}`. Deaktivierte oder unbekannte Geräte erhalten HTTP 404.

`config` enthält Identität, Alter, Avatar-Typ (`avatar`), den frei konfigurierbaren Avatar-Namen (`avatarName`), geordnete Seiten, Spiele und Home-Slots. `news` akzeptiert `limit` (1–100) und einen ISO-8601-Parameter `since`. `weather` und `aircraft` liefern providerunabhängige, standortbezogene Modelle und kennzeichnen einen bei Providerfehler weiter verwendeten Cache mit `stale: true`. `quiz` filtert mit `minAge <= device.age`. `checkin` akzeptiert `firmwareVersion`, `battery`, `wifiRssi` und `freeFlash`.

Bildassets sind stabile URLs und senden `Cache-Control: public, max-age=86400, immutable`.
