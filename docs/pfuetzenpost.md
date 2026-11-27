# Pfützenpost

Im Geräteeditor die Spieleseite und **Pfützenpost** für die teilnehmenden LEAPs
freigeben. Nach der Synchronisierung erscheint das Spiel ab Firmware 1.13.0.
Der erste LEAP öffnet einen Raum, weitere Geräte gelangen in den ältesten offenen
Raum. Sobald zwei bis vier Geräte verbunden sind, startet der Gastgeber per
Rechts Mitte. Startplatz, Würfel und Zugfolge bestimmt der Homeserver.

Die Spielzeit pro Zug beträgt 20 Sekunden. Verstreicht die Zeit, zieht der
Server die Frösche für den begonnenen oder automatisch gewürfelten Wurf.
Nach einem erkannten Verbindungsabbruch bleiben Platz und Restzeit für 30
Sekunden erhalten. Danach spielt der Raum mit mindestens zwei verbundenen oder
zurückkehrenden Spielern weiter. Alle Räume verwenden den bestehenden
Homeserver-Prozess. Ein Neustart beendet offene Partien. Die Webansicht
**Spielestatus** zeigt Lobby, Partie, Verbindungspause und Ergebnis.

## Geräteprotokoll v1

WebSocket unter `/api/v1/devices/{device_id}/pfuetzenpost/ws`. Das Gerät sendet
`{"type":"join","protocolVersion":1,"session":""}`. Eine bekannte Session-ID
stellt den bisherigen Platz wieder her. Der Server liest Name, Akzentfarbe und
Spielfreigabe aus der Gerätekonfiguration.

Die Kommandos `start`, `roll` und `stop` enthalten `seq` (steigende Eingabenummer)
und `turnId` aus dem letzten Spielstand. Der Server quittiert akzeptierte Eingaben
im nächsten Snapshot mit `ack`. `ping` hält die Verbindung aktiv. `leave` gibt den
Platz frei. Die Würfelwerte eines begonnenen Wurfs bleiben bis zum Stopp oder
Zugablauf im Server. Die Nachricht `state` enthält bei Änderungen unter anderem
die verfügbaren Plätze, die vorigen und aktuellen Froschpositionen, die zuletzt
enthüllten Würfel, die Spielphase und deren Restzeit. Zwischen Änderungen sendet
der Server kurze Heartbeats. Die Geräte animieren Würfel und Frösche lokal.
