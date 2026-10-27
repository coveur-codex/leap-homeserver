# Kooperatives Snake – 1.4.0-beta.1

Firmware und Homeserver verwenden Protokollversion 1. Im bisherigen Snake-Menü
stehen die drei Solo-Geschwindigkeiten und zusätzlich Multiplayer zur Auswahl.
Solo-Spiel, Rekord und Schwierigkeitswahl bleiben unverändert.

## Betrieb und Regeln

Der bestehende Uvicorn-Prozess ist der einzige Spielleiter. **Einen Worker**
betreiben (wie im Dockerfile); mehrere Prozesse/Server teilen keinen Spielzustand.
Es gibt genau eine automatisch verwaltete Partie, keine Raumauswahl. Während
sie läuft, erhalten neue Geräte eine Meldung; vorhandene Geräte können zurückkehren.
Spielzustand liegt ausschließlich im RAM. Ein Serverneustart beendet die Partie.
Die Firmware erkennt die verlorene Session und bietet über R Mitte einen Neustart an.

- 2–4 Geräte; zehn Sekunden Lobby ab dem ersten Beitritt, ohne Verlängerung.
  Anschließend drei Sekunden Startcountdown oder „Keine Mitspieler gefunden“.
- 40×13 Zellen wie Solo, 450 ms pro Bewegung (bisherige Standardgeschwindigkeit).
  120 Sekunden aktive Zeit; das Punkteziel beendet die Partie nicht.
- Zwei/drei/vier Spieler: sechs/acht/zehn Früchte und 20/30/40 Teampunkte als Ziel.
  Beides bleibt nach Verbindungsabbrüchen auf der Startspielerzahl festgelegt.
- Fremde Körper, vertauschte Köpfe und gemeinsame Zielfelder stoppen die
  betreffenden Schlangen. Körper gelten konservativ auch am wegziehenden
  fremden Schwanz als belegt. Eine freie Richtung kann beim nächsten Tick gewählt
  werden. Es entstehen keine Überlappungen und keine Punktabzüge.
- Wand/eigener Körper: drei Sekunden Pause, dann kurzer Körper an einer freien
  Position mit freier Vorwärtsstrecke. Falls kein Platz vorhanden ist, später erneut
  versuchen. 900 ms Schutz: ungültige Eigen-/Wandbewegungen stoppen statt auszuscheiden.
- Früchte werden auf freien, per Flood-Fill von lebenden Köpfen erreichbaren
  Zellen nachgefüllt. Bei Platzmangel bleiben vorübergehend weniger Früchte.
- Getrennte Spieler halten sofort an; fehlende Heartbeats nach drei Sekunden
  ebenfalls. Nach 15 Sekunden ohne Nachricht wird ihr Körper entfernt; der
  Teilnehmer bleibt für Wiederaufnahme bekannt. Ergebnisse bleiben drei Minuten
  verfügbar, sofern keine neue Partie eröffnet wird.

## WebSocket-Protokoll

`/api/v1/devices/{device_id}/snake/ws`, analog zum bestehenden Chat-Transport.
Nur bekannte aktivierte Geräte mit aktivierter Spieleseite und Snake dürfen beitreten.
Die Gerätekennung verwendet dieselbe Vertrauensgrenze wie die vorhandene Geräte-API.
Namen, Avatar-ID und Akzentfarbe kommen ausschließlich aus der Geräteverwaltung.
Weder Avatarbilder noch Farben werden von Steuerbefehlen übernommen.

Erste Nachricht innerhalb von fünf Sekunden:

```json
{"type":"join","session":""}
```

Nach jeder erfolgreichen Verbindung wird ein vollständiger `state` gesendet.
Für Reconnects sendet das Gerät die erhaltene Sessionkennung statt des Leerstrings.
Unbekannte/verlorene Sessions erzeugen `error`; sie eröffnen keine neue Lobby.
Weitere Nachrichten (maximal 512 Zeichen):

```json
{"type":"input","seq":1,"tick":0,"direction":0}
{"type":"ping"}
{"type":"sync"}
{"type":"leave"}
```

Richtungen: 0 oben, 1 unten, 2 links, 3 rechts. `seq` wächst je Teilnehmer,
Dubletten/ältere Nummern werden verworfen. Ein Tick akzeptiert einen gepufferten
Richtungswechsel ohne Umkehr. Eingaben müssen dem aktuellen oder unmittelbar
folgenden Tick zugeordnet sein; verspätete Eingaben werden nicht nachgeholt.
`players[].seq` bestätigt die höchste verarbeitete Eingabenummer auch nach Reconnect.
Ein Ping pro Sekunde hält die Verbindung aktiv; nach fünf Sekunden ohne Nachricht
schließt der Server den Socket. WebSocket-Heartbeat ergänzt die Anwendungspings.

`state` enthält `schemaVersion`, `session`, `revision`, `tick`, `phase`,
`remainingMs`, `score`, `target`, `columns`, `rows`, `stepMs`, `fruitCount`,
`food` und `players`. Zellen sind `[x,y]`. Spieler enthalten `id`, `avatar`,
`accentColor`, `connected`, `body`, `direction`, `seq`, `respawnMs`, `protected`.
Phasen: `lobby`, `countdown`, `playing`, `alone`, `finished`.
Deadline und Tick werden von einer monotonen Serveruhr bestimmt. Ein 50-ms-Timer
weckt die Simulation; Bewegung bleibt bei festen 450-ms-Schritten. Wiedereinstiege
haben eine eigene Dreisekunden-Deadline. Ergebnisse enden exakt an der
120-Sekunden-Deadline; Transport/Display können naturgemäß einige ms später folgen.

Jeder Zustand ist vollständig, daher ersetzt bei einem langsamen Empfänger der
neueste Zustand den vorherigen in einer Queue der Größe eins. Ein blockierter
Socket hat zwei Sekunden Sendezeit. Auch die Firmware hat eine solche Queue,
verwirft alte Revisionen/Ticks und frühere UI-Besuche. Keine Client-Simulation
oder Vorhersage: Bei diesem Rasterspiel mit 450 ms pro Schritt ist eine
Interpolation zwischen nicht bestätigten Zellen unnötig. Die Steuerung läuft in
einem eigenen FreeRTOS-Worker mit dem vorhandenen WebSockets-Client, TLS-CA und
Netzwerkprofil-Endpunkt. Nach 15 Sekunden ohne Zustand folgt eine Fehlermeldung.

## Automatische Spieleavatare

Die Quelle ist `data/pet/pagestatics/games.png` jedes veröffentlichten Avatarpakets,
auch mit äußerem Uploadordner. Explizite `pageStatics.games`-Metadaten werden ebenfalls
unterstützt. Nachrichtenbilder/Idle-Frames sind keine Spielebilder und werden nicht
ersatzweise in das Paket kopiert. Ohne Spielebild zeigt die Firmware einen Platzhalter.

`game-avatars` ist ein automatisch versioniertes `common`-Paket mit `portraitSize:80`
und `avatarSources[avatar-id] = {source:Quellhash,image:Dateipfad}`. Geeignete transparente
80×80-PNGs behalten ihre Bytes, sonst wird proportional auf einer transparenten
80×80-Fläche verkleinert. Hashvergleich verhindert unnötige neue Versionen.
Avatarneuanlage, Bildänderung und Entfernung werden bei der regulären
`ensure_packages`-Generierung (Start, Assetansicht, Geräte-Sync) berücksichtigt.
Keine Migration, keine neue Bildersammlung und keine neuen Abhängigkeiten.
Das Paket verwendet die vorhandenen unveränderlichen Manifeste, SHA-256-Blobs,
Sync-Aktivierung und Bereinigung. Alle Geräte erhalten es unabhängig von ihrem
Avatar oder der Chat-Freigabe; Stable-/Beta-Firmwareverteilung bleibt bestehen.

## Abnahme

Automatisiert: Lobbygrenzen/Belegung/Reconnect, autoritative Countdown-/Endzeit,
Punkt-/Fruchtstaffelung, Eingabereihenfolge, gleichzeitige Kollisionen, Dreisekunden-
Wiedereinstieg, Schutz, Flood-Fill und 1000 Schritte mit Belegungsinvarianten;
Asset-Hashreuse/Update/Entfernung sowie bestehende Homeserver-Regressionstests.
Firmware: nativer Socket-Worker mit realem JSON-Decoder, Queues/Reconnect/Timeout;
Spiele-Lifecycle und Lobby-/Arena-Geometrie inklusive unveränderter Solo-Tests.

Vor produktiver Freigabe mit zwei, drei und vier NV3007-Geräten prüfen:
Avatartransparenz und Akzentfarben (auch gleiche Farben), 3–2–1 und gemeinsames
Ende, Eingabelatenz, gleichzeitige Kopfkollision, Wand/Selbstkollision und
Wiedereinstieg, WLAN-Aussetzer unter/über 15 Sekunden, Serverneustart und neue
Partie. Diese Hardwareprüfung ist in der Entwicklungsumgebung nicht möglich.
