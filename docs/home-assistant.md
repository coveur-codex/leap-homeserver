# LEAP-Zimmersteuerung mit Home Assistant

Ab Homeserver **1.5.0-beta.2** und Firmware **1.5.0-beta.2**.

Die neue Firmwareseite **Mein Zimmer** steuert eine Heizung und null bis zwei
Lampen über den LEAP-Homeserver. Home Assistant benötigt dafür keine zusätzliche
Integration und keine YAML-Automationen. Alle Befehle bleiben normale HA-Serviceaufrufe;
vorhandene Zeitpläne und Automationen können sie später wieder überschreiben.

## Einrichtung

1. Homeserver-Datenverzeichnis sichern. Diese Version ergänzt Migration `0022`
   nach `0021`. Die vorhandenen Seiten, ihre Reihenfolge und Inhalte bleiben bestehen;
   die neue Seite wird hinten angehängt. Bei anderen Migrationsständen vor dem
   Installieren die Versionslinie abgleichen, nicht die Datenbank zurücksetzen.
2. Im Home-Assistant-Benutzerprofil unter **Sicherheit → Langlebige Zugriffstoken**
   ein Token erstellen. Lokal in der `.env` des Homeservers eintragen:

   ```dotenv
   LEAP_HOME_ASSISTANT_URL=http://homeassistant.local:8123
   LEAP_HOME_ASSISTANT_TOKEN=hier_dein_lokal_erzeugtes_token
   ```

   Das Token bleibt ausschließlich am Homeserver. Es wird weder in der Geräte-
   konfiguration noch in API-Fehlern oder Firmwaredateien ausgegeben.
3. Homeserver aktualisieren, beispielsweise `docker compose up -d --build`.
   Der Container führt Migrationen beim Start aus. Bei nativer Installation:
   `alembic upgrade head`, anschließend den Server neu starten.
4. Unter **Geräte → Gerät bearbeiten → Mein Zimmer · Home Assistant** die
   Zuordnung prüfen und bei Bedarf ändern. Für bestehende Geräte werden die unten
   genannten Zuordnungen bei der Migration automatisch angelegt; neue Geräte mit
   diesen IDs erhalten dieselben Startwerte. Andere Geräte starten mit deaktivierter
   Zimmerseite. Das Duplizieren übernimmt keine Zimmerzuordnung.
5. Firmware **1.5.0-beta.2** mit dem bestehenden Arduino-/CI-Verfahren bauen und
   zunächst auf `leap-papa` testen. Erst den Homeserver, dann die Firmware aktualisieren.
   Die Beta-Dateiversion muss beim Firmware-Upload exakt übereinstimmen. Nach dem
   Gerätesync erscheint **Mein Zimmer**. Kein Home-Assistant-Token im Sketch nötig.

### Zuordnungen

| LEAP-Gerät | Heizung | Lampen |
| --- | --- | --- |
| leap-papa | climate.heizung_homeoffice | keine |
| leap-erik | climate.heizung_lars_erik | light.einfahrt_garage, light.erik_tisch |
| leap-lars | climate.heizung_lars_erik | light.lars_hochbett, light.lars_tisch |
| leap-anna | climate.trv_z01_80_7 | light.lichterkette_anna |

Alle Zieltemperaturen liegen zwischen **10 und 30 °C**. Engere Gerätegrenzen aus
Home Assistant werden zusätzlich berücksichtigt. Eine Änderung beträgt exakt
1 °C relativ zur aktuellen Zieltemperatur (20,5 → 21,5), nicht zur Raumtemperatur.
Die Heizung muss eine einzelne Zieltemperatur unterstützen und HA muss Celsius
verwenden. Erik und Lars bedienen **denselben** Sollwert. Ihre geöffneten Zimmerseiten
holen den Zustand alle drei Sekunden neu; langsame Thermostatrückmeldungen können
zusätzliche Verzögerung verursachen.

[Beispielzuordnungen als JSON](examples/room-assignments.json): Referenz für die
Felder im Geräteeditor, keine automatisch eingelesene Konfigurationsdatei.

## Bedienung am Gerät

Alle folgenden Tasten sind am **rechten** Richtungsschalter:

- Hoch/runter: Heizung oder Lampe auswählen.
- Heizung links/rechts: Zieltemperatur lokal −1 / +1 °C vorwählen.
- Lampe links/rechts: direkte Farbkachel wechseln; Schwarz bedeutet Aus.
- Farben: Weiß, Gelb, Orange, Rot, Rosa, Lila, Blau, Hellblau, Türkis und Grün.
- Nach **einer Sekunde ohne weitere Wertänderung** werden die gewählten Endwerte
  automatisch übertragen. Mehrere Schritte verursachen einen Sollwertaufruf,
  keine Folge einzelner Gradänderungen. Mitte ist nicht erforderlich.

Der linke Schalter navigiert wie bisher zwischen Seiten und zum Menü.
Die bereits gewählte Übernahme läuft auch beim Verlassen der Seite weiter.
„Weiß“ ist ein warm wirkender RGB-Wert, keine Kelvin-Einstellung.
Farben sind bei `hs`, `xy`, `rgb`, `rgbw` oder `rgbww` verfügbar; reine Dimmer
wechseln zwischen Schwarz/Aus und Weiß/An. Andere HA-Farben werden anhand des
RGB-Werts der nächstliegenden Kachelfarbe zugeordnet.

## Rückmeldungen und Grenzen

- Anzeigen basieren auf gelesenen HA-Zuständen, nicht auf erfundenen Erfolgsmeldungen.
  „Gesendet“ bedeutet angenommener Serviceaufruf, keine physische Lampenbestätigung.
- Das Gerät sammelt Eingaben bis zur einsekündigen Pause. Lokale Vorschauen mit
  Stern bleiben bei Abfragen und während eines Requests erhalten. Neuere Eingaben
  werden anschließend als neuer Endwert übertragen. Betroffene Geräte werden
  nacheinander verarbeitet. Es gibt keine gespeicherte Offline-Warteschlange und
  keine automatische Wiederholung fehlgeschlagener Befehle.
- Heizungsänderungen auf dieselbe Entity werden serverweit nacheinander verarbeitet.
  Neue absolute Endwerte ersetzen auch noch unbestätigte frühere Sollwerte. Alte
  Firmware kann weiterhin relative Schritte senden; diese warten bei ausstehender
  Bestätigung höchstens 15 Sekunden. Für die Serialisierung den Homeserver wie
  mitgeliefert mit **einem Uvicorn-Worker** betreiben.
- Nach zehn Sekunden ohne erfolgreichen Abruf oder bei fehlendem WLAN wird der
  angezeigte Stand als veraltet behandelt und die Steuerung gesperrt. Zustände
  bleiben im RAM; regelmäßige Abfragen schreiben nicht ins Geräte-Flash.
- Nicht erreichbare oder fehlende Entities werden einzeln als nicht verfügbar
  dargestellt. Ein falsch benanntes Licht blockiert nicht die anderen Geräte.
- Die Geräte-API verwendet wie die bestehende LEAP-API die Geräte-ID ohne eigene
  Geräteauthentifizierung. Die Zuordnung beschränkt die angebotenen Aktionen,
  bietet aber keine Zugriffstrennung gegen nachgeahmte Geräte-IDs. Die `/room`-API
  nur im vertrauenswürdigen Heimnetz betreiben bzw. am vorhandenen externen
  Reverse-Proxy sperren. Nicht ungeprüft öffentlich weiterleiten.

## Verbindung und Abnahme

`homeassistant.local` muss **aus dem laufenden Homeserver-Container** auflösbar sein.
Docker unterstützt mDNS-Namen je nach Host nicht automatisch. Falls nötig in
`LEAP_HOME_ASSISTANT_URL` die feste LAN-IP von Home Assistant verwenden und den
Container neu erstellen. Der HA-Zugriff verwendet diese lokale Adresse direkt,
keinen System-HTTP-Proxy. Für die Cloud-Entwicklungsumgebung besteht kein Zugang
zum Heimnetz; ein Live-Test und ein ESP32-/Displaytest sind lokal erforderlich.

Nach dem Einrichten zunächst nur lesen:

```sh
curl http://localhost:8080/api/v1/devices/leap-papa/room
```

Danach am Gerät prüfen: ein Schritt wärmer und zurück; 10/30-°C-Grenzen;
Erik/Lars mit gemeinsamem Sollwert; jede Lampe einzeln; alle Farben;
Heizung im HA-Heizplan; WLAN aus/an ohne nachträglich ausgeführte Befehle.
Die effektiven Heizgrenzen sind in `climate.minimum` und `climate.maximum` sichtbar.

Optional zum Vergleich in **Home Assistant → Entwicklerwerkzeuge → Aktionen**
(diese Beispiele werden manuell ausgeführt und verändern echte Geräte):

```yaml
action: climate.set_temperature
target:
  entity_id: climate.heizung_homeoffice
data:
  temperature: 21
```

```yaml
action: light.turn_on
target:
  entity_id: light.erik_tisch
data:
  rgb_color: [180, 0, 255]
```

## LEAP-API

`GET /api/v1/devices/{device_id}/room` liefert `schemaVersion: 1`, `climate`,
`lights` (in Zuordnungsreihenfolge, mit `color` als nächstliegender Palette),
`colors` und `temperatureSetSupported: true`. Ein POST auf denselben Pfad nimmt
nur vordefinierte Ziele und Aktionen entgegen, keine freien Entity-IDs:

```json
{"target": "climate", "action": "set_temperature", "temperature": 24}
```

Die bisherige relative Aktion `warmer`/`colder` bleibt für alte Geräte verfügbar.

```json
{"target": "light0", "action": "off"}
```
```json
{"target": "light1", "action": "color", "color": "lila"}
```

Ziele: `climate`, `light0`, `light1`; Aktionen: `set_temperature` mit `temperature` (10–30 °C), `warmer`, `colder`, `on`,
`off`, `color` passend zum Ziel. Farbwerte sind serverseitig fest definiert.
403: nicht zugeordnet/deaktiviert; 404: Gerät fehlt/deaktiviert; 409: Grenze,
fehlende Bestätigung oder Gerät nicht steuerbar; 422: ungültige Eingabe;
503: fehlendes Token, falsche Serveradresse oder HA nicht erreichbar.
