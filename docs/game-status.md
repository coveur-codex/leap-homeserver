# Spielestatus – 1.4.0

`/games` ist die Live-Übersicht aller registrierten serververwalteten Spiele.
Die Seite verwendet das vorhandene Design und zeigt initial einen vollständigen
Status auch ohne JavaScript. Danach wird alle fünf Sekunden `/games/status`
als HTML-Ausschnitt geladen. Anfragen überlappen sich nicht; bei Fehlern bleibt
der letzte Stand mit Unterbrechungshinweis sichtbar. Alle Antworten sind `no-store`.

`GET /api/v1/games/status` bietet dieselben Informationen als JSON:

- `schemaVersion: 1`, `generatedAt` (UTC), `runningSessions`, `waitingSessions`
- `games[]`: `id`, `name`, `error` und `sessions[]`
- Eine Session: `session_id`, spielbezogene `phase` und `label`,
  `activity` (`waiting`, `running`, `finished`), `remaining_ms`, `max_players`,
  `players[]` mit `device_id` und `connected`, sowie `metrics[]` mit `label`/`value`.

Damit sind mehrere Spiele und mehrere gleichzeitige Sessions je Spiel möglich.
Das HTML-Template kennt keine Snake-Felder; auch Kennzahlen werden allgemein
angezeigt. Ein fehlerhafter Statuslieferant markiert sein Spiel als nicht verfügbar,
beeinträchtigt aber nicht die übrige Übersicht. Es werden keine Zugangsdaten,
Avatarbilder oder vollständigen Spielfeldzustände ausgeliefert.

## Ein weiteres Spiel anbinden

In `app/services/game_status.py` stehen die unveränderlichen Datentypen
`GameSession`, `GameParticipant` und `GameMetric`. Ein Spielservice implementiert
einen schnellen, rein lesenden Statuslieferanten, der ein Tupel von Sessions
liefert (leer bedeutet „Keine Partie aktiv“). Beim Anwendungsstart registrieren:

```python
from app.services.game_status import registry
registry.register("other_game", "Weiteres Spiel", other_game_service.status)
```

Die `game_id` bleibt stabil; die Phase ist Sache des Spiels. `activity` steuert
die gemeinsamen Zähler. `label` ist der sichtbare deutsche Statustext.
Statuslieferanten führen keine Netzwerk-/Datenbankarbeit, keine Simulation und
keine Warteschleifen aus. Anbieter und asynchrone Leser laufen auf demselben
ASGI-Eventloop wie die autoritative Simulation, damit keine parallelen
Worker-Threads die veränderlichen Spielobjekte lesen. Die serialisierten Antworten
sind vom Spielzustand getrennt. Neue Spieltypen brauchen keine Template-/JS-Änderung.

Snake ist der erste Anbieter. Er liest die vorhandene `SnakeHub`-Instanz und
verwendet die gleiche Restzeitberechnung wie die Geräte. Ein Ergebnis zählt nicht
mehr als laufendes Spiel. Ohne Session ist Snake explizit inaktiv. Solo-Spiele auf
den Geräten werden nicht erfasst, da hierfür keine Laufzeit-Telemetrie existiert.
Es bleibt bei einem Uvicorn-Worker für diese zentrale In-Memory-Spielverwaltung;
Neustart verwirft laufende Sessions. Die Übersicht legt keine zweite Raumverwaltung
und keine zusätzliche Datenbank-Historie an.

Vier Gewinnt registriert ebenfalls einen Statuslieferanten. Er liefert mehrere
parallele Zweierpartien mit Runde und Zuganzahl; Verbindungspausen zählen als
laufende Partie. Die Restzeit entspricht je nach Phase Such-, Zug- oder
Wiederverbindungsfrist. Regeln: [Vier Gewinnt](connect-four-multiplayer.md).
