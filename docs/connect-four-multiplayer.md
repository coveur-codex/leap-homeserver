# Vier Gewinnt: Multiplayer – 1.5.2

Der Homeserver ist der Spielleiter. Mehrere unabhängige Partien laufen parallel,
mit genau zwei Geräten pro Spiel. Neue Geräte werden dem ältesten wartenden,
verbundenen Gerät zugeordnet. Eine bereits laufende Partie erhält keine weiteren
Spieler. Ein Gerät kann nur einer aktuellen Partie zugeordnet sein.

## Betrieb

Zuerst Homeserver 1.5.2, anschließend Firmware 1.5.2 installieren und die
Gerätekonfiguration synchronisieren. Die Spieleliste enthält bereits `connect_four`.
Die Spieleseite und Vier Gewinnt müssen für das Gerät aktiviert sein.
Die bestehenden Solo-Schwierigkeitsstufen bleiben lokal verfügbar.

Die Akzentfarbe kommt aus der vorhandenen Geräteverwaltung (`Device.accent_color`,
`config.accentColor`), die Spielfreigabe aus `Device.enabled_games`.
Keine neue Farbverwaltung und keine neue Datenbankmigration erforderlich.
Namen und Farben der Mitspieler stammen ausschließlich vom Server.
Punkt und Kreuz kennzeichnen die Spieler auch bei gleichen Farben.

**Nur einen Uvicorn-Worker betreiben**, wie im vorhandenen Dockerfile. Partien
liegen im RAM dieses Prozesses. Ein Serverneustart beendet sie; die Firmware
bietet danach die erneute Modusauswahl an. Ergebnisse bleiben 180 Sekunden für
Wiederverbindungen erreichbar. Maximal 256 aktuelle/aufbewahrte Partien begrenzen
den Speicherbedarf; bei Erreichen der Grenze wird eine neue Suche abgewiesen.
Es gibt keine Änderungen an der Geräte-API-Vertrauensgrenze: bekannte aktivierte
Geräte im vertrauenswürdigen Heimnetz, Gerätekennung wie bei den bestehenden APIs.

## Regeln und Bedienung

- „Vier Gewinnt“ bietet Leicht, Mittel, Schwer und Multiplayer.
- Automatische Suche für höchstens 30 Sekunden. Ohne Mitspieler kehrt die
  Firmware mit einem Hinweis ins Spielemenü zurück. L Mitte bricht ab.
- Standardfeld 7×6 mit Schwerkraft, vier gleiche Steine waagerecht, senkrecht oder
  diagonal gewinnen. Ein volles Feld ohne Sieger ist unentschieden.
- Der Server lost den ersten Startspieler aus. R Links/Rechts wählt die Spalte,
  R Mitte wirft ein. Nur der aktuelle Spieler kann einwerfen. Volle Spalten und
  doppelte/veraltete Eingaben verändern das Feld nicht.
- 30 Sekunden pro Zug. Die Frist beginnt mit dem Spielstart bzw. einem gültigen
  Zug. Bei Ablauf gewinnt der Gegner; ungültige Züge verlängern sie nicht.
- Verbindungsabbruch pausiert die Runde und die verbleibende Zugzeit. Fehlende
  Anwendungspings werden nach drei Sekunden als Abbruch gewertet. Innerhalb von
  30 Sekunden kann dasselbe Gerät wieder einsteigen. Dann läuft die restliche
  Zugzeit weiter. Nach Ablauf gewinnt ein noch verbundener Gegner; ohne
  verbundenen Spieler endet die Runde ohne Sieger.
- L Mitte verlässt die Partie ausdrücklich; ein verbundener Gegner gewinnt sofort.
- R Mitte nach Spielende stimmt einer Revanche zu. Erst wenn beide noch anwesenden
  Spieler zugestimmt haben, wird das Feld geleert. Der Startspieler wechselt.

## WebSocket-Protokoll v1

`/api/v1/devices/{device_id}/connect-four/ws`

Erste Textnachricht innerhalb von fünf Sekunden, höchstens 512 Zeichen:

```json
{"type":"join","protocolVersion":1,"session":""}
```

Leere Session sucht eine Partie oder stellt eine vorhandene aktive Mitgliedschaft
wieder her. Für Wiederverbindung wird die erhaltene 32-stellige Session gesendet.
Fremde, abgelaufene und nach Serverneustart verlorene Sessions werden abgewiesen;
sie erzeugen keine neue Partie. Ein neuer Socket ersetzt den alten desselben
Geräts. Dessen späteres Ende darf den neuen Socket nicht abmelden.

Weitere Textnachrichten (jeweils höchstens 512 Zeichen):

```json
{"type":"ping"}
{"type":"sync"}
{"type":"input","seq":1,"round":1,"move":0,"column":3}
{"type":"rematch","seq":2,"round":1}
{"type":"leave"}
```

`column`: 0–6. `seq`: positive, je Teilnehmer über alle Runden steigende
32-Bit-Zahl; bestätigte Werte stehen in `players[].seq`. `round` und `move`
ordnen Eingaben einer konkreten Runde und einem konkreten Feld zu. Verzögerte
Eingaben können so nicht in einer späteren Runde landen.

Alle 250 ms sendet der Server einen vollständigen Zustand mit `type: "state"`,
`schemaVersion: 1`, `session`, `revision`, `phase`, `remainingMs`, `board` (6 Zeilen
mit je 7 Werten: 0 leer, 1/2 Spieler), `turn`, `move`, `round`, `winner` und
`reason`. `players` enthält ein oder zwei Objekte mit `id`, `name`, `accentColor`,
`connected`, `seq`, `rematch`, `left`.

Phasen: `lobby`, `playing`, `paused`, `finished`. `remainingMs` gibt je nach Phase
Suchzeit, Zugzeit oder Wiederverbindungszeit an; nach Spielende 0.
Spielendgründe: `four`, `draw`, `turn_timeout`, `disconnect_timeout`, `left`,
`no_opponent`. Fehler haben `type: "error"` und `code`.

Eine monotone Serveruhr entscheidet Fristen, bevor ein neuer Zug verarbeitet
wird. Pro Socket gibt es genau einen Sender; ein Sendeversuch ist auf zwei
Sekunden begrenzt. Anwendungspings einmal pro Sekunde, Empfangsfrist fünf Sekunden.
Die Firmware nutzt einen eigenen FreeRTOS-Netzwerkworker, die bestehenden
Netzwerkprofile und TLS-CA-Prüfung. Eine Queue hält nur den neuesten Zustand;
UI-Generationen und Revisionen verhindern die Übernahme alter Zustände.
Die Firmware simuliert keine gegnerischen Züge. Ihr 40-Sekunden-Transporttimeout
lässt die serverseitige 30-Sekunden-Wiederverbindung zu.

## Prüfung

Servertests prüfen parallele Partien, Gerätebelegung, alle Siegrichtungen,
Unentschieden, volle Spalten, ungültige/veraltete Eingaben, exakte Fristen,
Verbindungspause, Reconnect, Revanche, Aufbewahrung sowie echte ASGI-WebSockets
mit vier Geräten und Freigabe-/Identitätsprüfungen.
Native Firmwaretests prüfen den echten Decoder und Socketworker inklusive
Reconnect, Sequenzbestätigung, Revanche, Verlassen, alter UI-Generationen und
`millis()`-Überlauf. Die Games-Lifecycle-Tests prüfen Eingaben, fehlende lokale
Vorhersage/KI, Farb-/Symbolanzeige, Displaygrenzen und Rückkehranforderung.

Vor einem Geräte-Rollout: mit vier realen LEAPs zwei gleichzeitige Partien,
identische Akzentfarben, Menü-Rückkehr nach 30 Sekunden, Zugablauf,
WLAN-Ausfall unter/über 30 Sekunden und Revanche überprüfen.

Die vorhandene Seite **Spielestatus** zeigt alle Vier-Gewinnt-Partien mit Phase,
Teilnehmern, Restzeit, Runde und Zuganzahl neben Snake. Ein Hintergrundtimer
prüft Fristen und Aufbewahrung auch dann, wenn alle Geräte getrennt sind.
