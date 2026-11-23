# Rangierwerk auf dem Homeserver

Im Geräteeditor unter **Spiele** Rangierwerk aktivieren, die Spieleseite
einschalten und das Gerät synchronisieren. Für den gemeinsamen Bahnhof
benötigen die Geräte Firmware 1.11.0. Die gemeinsam gespielte Schwierigkeit
steht unter **Spielestatus → Rangierwerk-Einstellungen**. Es stehen die vier
Stufen Kleiner Bahnhof, Rangiermeister, Güterbahnhof und Großer Rangierbahnhof
zur Verfügung. Standard ist Stufe 1. Die Einstellung bleibt in SQLite
gespeichert und gilt ab der nächsten Karte.

Bis zu vier Geräte können einer einzigen Welt jederzeit beitreten. Sie
bekommen je einen Lokschuppen und die hinterlegte Geräte-Akzentfarbe. Eine
volle Welt meldet den Geräten, dass sie warten müssen. Bei einem kurzen
Verbindungsverlust bleibt dieselbe Lok erhalten. Nach 60 Sekunden wird der
Platz frei und die Wagen bleiben auf ihrer Position.

Die Karte läuft zehn Minuten, solange mindestens ein Gerät verbunden ist.
Danach erscheint drei Sekunden lang das gemeinsame Ergebnis und die Loks
werden auf der nächsten Karte neu eingereiht. Bei vier verbundenen Geräten
gibt es vier statt drei offene Aufträge. Wenn ein Gerät geht, bleibt der
zusätzliche Auftrag bis zum regulären Abschluss offen. Eine Karte und ihre
Wagen liegen im Speicher des Homeserver-Prozesses. Beim Serverneustart wird
ein neuer Bahnhof aufgebaut. Wie die vorhandenen Multiplayer-Spiele läuft
diese gemeinsame Welt in einem Uvicorn-Worker.

[Spielidee, Einzelspieler und Steuerung](https://github.com/coveur-codex/leap-firmware/blob/main/docs/rangierwerk.md)

## WebSocket v1

Geräte verbinden sich über `/api/v1/devices/{device_id}/rangierwerk/ws`.
Der Server prüft die Gerätefreigabe beim Beitritt und während der Verbindung.
Die aktuelle Geräte-Akzentfarbe kommt aus der Datenbank.

| Gerät → Server | Felder |
| --- | --- |
| `join` | `protocolVersion: 1` |
| `ping` | Anwesenheit erhalten |
| `drive` | `card`, `seq`, `direction` (-1, 0 oder 1). Bei gedrücktem Schalter regelmäßig erneuern. |
| `turnout` | `card`, `seq`, `index` der Weiche |
| `split` | `card`, `seq`, die beiden benachbarten Fahrzeug-IDs `a` und `b` |
| `recover` | `card`, `seq`. Eigene stehende Lok in den Schuppen holen. |
| `leave` | Teilnehmerplatz sofort freigeben |

`seq` muss für Eingaben je Verbindung steigen. `card` identifiziert den
aktuellen Bahnhof. Alte Karten, doppelte Befehle und inzwischen geänderte
Kupplungen werden ignoriert. Ein Fahrbefehl verfällt nach 450 ms. Nach spätestens
3,5 Sekunden ohne Anwesenheitsmeldung beginnt die Platzreservierung.

Der Server sendet etwa alle 120 ms einen vollständigen `state` mit
`protocolVersion`, `card`, `seed`, `difficulty`, `remainingMs`, `summary`,
`self` (eigener Lokplatz), `switches` (Bitmaske) und `delivered` (Teamzahl).

- `colors` enthält `[Lokplatz, Akzentfarbe, Anzeigename, verbunden]`.
- `vehicles` enthält `[Platz, ID, Gleisknoten, Richtungsknoten, Gütertyp,
  EntladezeitMs, KupplungA, KupplungB, RichtungZumRichtungsknoten]`.
  Kupplungen verweisen auf Fahrzeugplätze. `255` steht für einen fehlenden
  Knoten, Gütertyp oder Kupplungspartner. Die Plätze 0–3 sind für Loks reserviert.
- `orders` enthält offene Aufträge als `[ID, Gütertyp, Sollzahl, geliefert]`.
  Gütertypen 0–4 entsprechen Holz, Stein, Kohle, Paketen und Tankwagen.
  Der Zielknoten stammt wie der Weichenindex aus dem deterministischen Gleisplan.
- `full` meldet eine belegte Welt. `error` enthält einen Fehlercode.

Der Server benutzt eine kleine C-Schnittstelle für `app/native/Yard.h`. Die
Datei wird zusammen mit der identischen Firmware-Kopie gepflegt. Das
Docker-Build kompiliert die Bibliothek automatisch. Für lokale Entwicklung
siehe [README](../README.md). Tests bauen die Bibliothek aus dem aktuellen
Quellstand.
