# ESP32-Synchronisation

1. Nach WLAN-Verbindung `GET /api/v1/devices/{id}/sync` abrufen.
2. Lokale Versionszähler vergleichen. Nur geänderte Bereiche laden: `/config`, `/news`, `/weather`, `/quiz`.
3. JSON und Assets zunächst temporär speichern, validieren und dann atomar als aktuellen Datenstand markieren.
4. Bilder aus dem jeweiligen `image`-Pfad laden. URLs bleiben stabil und sind cachebar.
5. Erfolgreichen Datenstand und Versionszähler in persistentem Flash sichern. Bei Netzfehlern unverändert mit dem letzten vollständigen Stand arbeiten.
6. Regelmäßig `POST /checkin` senden. Ein Check-in ist keine Voraussetzung für die Offline-Nutzung.

News kann über `since` inkrementell geladen werden; Geräte sollten dennoch auf Artikel-ID deduplizieren. Wetter wird als kleiner Snapshot ersetzt. Antworten externer Provider dürfen nie direkt verarbeitet werden. Empfohlen sind kurze HTTP-Timeouts, exponentielles Backoff und keine dauerhafte Verbindung.
