# Radio (Homeserver/Firmware 1.6.0)

Vor dem Start `alembic upgrade head` ausführen (Schema **0024**). Bestehende
Geräte erhalten eine deaktivierte Radio-Seite ohne Freigaben; bestehende
Seitenreihenfolgen und Einstellungen bleiben erhalten. Neue Geräte starten
ebenfalls ohne Radio. Es gibt keine automatisch freigegebenen Standardsender.

Unter **Radio** Sender mit Name, direkter HTTP-/HTTPS-MP3-URL, Aktiv-Schalter und
Positionsnummer anlegen, bearbeiten und löschen. Tabellen, Formulare, Aktionen,
Jinja-Templates und SQLAlchemy-Speicherung folgen der News-Feed-Verwaltung.
Position und bei Gleichstand Sender-ID bestimmen die Reihenfolge. Playlists und
bekannte andere Audioformate werden beim Speichern abgewiesen; ob ein Endpunkt
tatsächlich MP3 sendet, prüft das Gerät beim Abspielen. Der Server ruft keine
Stream-URLs ab. URLs dürfen keine Zugangsdaten oder Fragmente enthalten.

Unter **Geräte → Gerät bearbeiten → Seiten** Radio aktivieren. Im Abschnitt
**Radio** werden die zentralen Sender wie die bestehenden Inhalts-/News-Auswahlen
per Checkbox freigegeben. Bis zu 32 Sender pro Gerät; inaktive Sender bleiben in
der Auswahl als solche gekennzeichnet, werden aber keinem Gerät geliefert.
Freigaben verwenden wie `included_feed_ids`/`excluded_feed_ids` eine JSON-ID-Liste
am Gerät (`radio_station_ids`), keinen neuen Konfigurationsdienst. Kopieren eines
Geräts übernimmt Freigaben und Seiteneinstellungen. Löschen eines Senders entfernt
seine ID aus allen Gerätefreigaben in derselben Transaktion.

## Synchronisierung

Der bestehende Konfigurations-Endpunkt liefert zusätzlich:

```json
{"radioStations":[{"id":42,"name":"Mein Radio","url":"https://example.org/live.mp3"}]}
```

Nur explizit freigegebene, zentral aktive Sender einer aktivierten Radio-Seite
werden geliefert. Geräte ohne Radio oder Freigaben erhalten `[]`. Senderänderung,
Sortierung, Aktivierung und Löschung erhöhen `config_version` der zugeordneten
Geräte; Änderungen im Geräteformular verwenden den bisherigen Versionsschritt.
Versionsabfrage, Sync-Plan, `configUrl` und atomarer Firmware-Snapshot bleiben der
bestehende Übertragungsweg. Es gibt keinen zweiten Radio-Sync und keinen Proxy.
Vorübergehend nicht erreichbarer Homeserver verhindert die Nutzung des letzten
Snapshots nicht. Entzug einer Freigabe stoppt bzw. ersetzt die Wiedergabe, sobald
die neue Konfiguration auf dem Gerät angewendet wurde.

## Bedienung auf dem Gerät

Radio startet beim Öffnen der Seite mit dem letzten noch freigegebenen Sender,
sonst dem ersten verfügbaren. Rechter Taster links/rechts wechselt Sender,
hoch/runter ändert die Lautstärke um fünf Prozentpunkte, Mitte wiederholt einen
fehlgeschlagenen Verbindungsaufbau. Linke Navigation bleibt unverändert.
Menü, Sperre, andere Seiten und OTA beenden Radio. Fehlendes WLAN, Verbindungs-,
Format- und Pufferfehler erscheinen als kurzer Status; es gibt keinen automatischen
endlosen Wiederverbindungsversuch.

## Validierung

`pytest` deckt Sender-CRUD, URL-Validierung, Sortierung, getrennte Gerätefreigaben,
Sperren, zentrale Deaktivierung, Löschbereinigung, `configVersion`/Sync-Pläne,
Seiten-Deaktivierung, Formular-Rendering und Schema-Upgrade/-Downgrade ab.
Zusätzlich wurde der Formularablauf in Chromium mit Playwright geprüft.
Echte WLAN-/TLS-Radiosender, Lautsprecher und ESP32-Hardware müssen am Zielgerät
abgenommen werden. Decoder, RAM-Budget und Flash-Vergleich stehen in
`leap-firmware/docs/radio.md` und `docs/radio-validation.md` des Firmware-PRs.
