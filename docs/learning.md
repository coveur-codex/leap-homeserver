# Lernwelt (Homeserver 1.8.0, Firmware 1.9.0)

In Geräte → Seiten „Lernwelt“ aktivieren und wie jede andere Seite sortieren.
Der Seitenname öffnet die kontextbezogenen Einstellungen: Mathe-Labor und
SilbenTrainer unabhängig freigeben. Das vorhandene Mathe-Labor-Zielzahlenformular
ist in diese Ansicht verschoben; Endpoint, Zahlenbereiche und `Device.math_lab`
bleiben unverändert.

Beim SilbenTrainer sind verfügbare Stufen (mindestens eine), Standardmodus,
10/15 Aufgaben, feste/Zufallsreihenfolge und automatischer Wechsel
(Aus/5/10/15 s) konfigurierbar. Kinder können am Gerät innerhalb der freigegebenen
Stufen wählen. Erweiterte JSON-Felder ergänzen je maximal 32 Silben und Wörter:

```json
{
  "applications": [
    {"id": "math_lab", "enabled": true},
    {"id": "syllable_trainer", "enabled": true}
  ],
  "syllableTrainer": {
    "levels": [1, 2, 3],
    "defaultMode": 0,
    "sessionLength": 10,
    "random": true,
    "autoSeconds": 0,
    "syllables": [{"text": "WE", "level": 1}],
    "words": [{"word": "WIESE", "syllables": ["WIE", "SE"], "level": 3}]
  }
}
```

Dies ist `pages[].settings` der Seite `learning` aus der vorhandenen Config-API,
kein neuer Endpoint. Modus 0 = Silben lesen, 1 = Silben verbinden, 2 = Wörter
lesen. Stufe 1 = leicht, 2 = mittel, 3 = schwer. Alle Wörter sind redaktionell
gegliedert, auf dem Gerät erfolgt keine automatische Silbentrennung.
Großbuchstaben A–Z/ÄÖÜ, maximal 6 Buchstaben je Silbe, 16 je Wort, 2–5 Silben
je Wort. Die Silben müssen zusammen exakt das Wort ergeben. Der Server weist
ungültige Inhalte mit HTTP 422 zurück, bevor die Konfiguration geändert wird.
Pädagogische Gliederung und Schwierigkeitsstufe müssen die betreuenden Personen
prüfen. Doppelte Wörter ersetzen die mitgelieferte Gliederung nicht.

Speichern erhöht `configVersion`; der reguläre Sync und Firmware-Snapshot
übernehmen auch eigene Inhalte für den Offlinebetrieb. Das Duplizieren von
Geräten übernimmt Freigaben, Stufen und eigene Inhalte. Merkeinträge bleiben
lokal auf dem Gerät. Es gibt keine Leistungsprotokolle, Audiofunktionen,
Onlineübung, zusätzlichen Scheduler oder neue Abhängigkeit.

Migration **0026** hängt Lernwelt hinter die bestehenden Seiten, ohne Reihenfolge,
Seitenparameter, `enabled_games`, `math_lab` oder Lernfortschritte umzuschreiben.
Ihre Aktivierung übernimmt die bisherige Spiele-Aktivierung; die Mathe-Labor-
Freigabe übernimmt die bisherige Auswahl in `enabled_games`. SilbenTrainer ist
innerhalb der Region zunächst freigegeben. Neue Geräte starten mit beiden Apps.
Die aktuelle Spieleliste enthält `math_lab` nicht mehr. Zuerst den Homeserver,
dann die Firmware aktualisieren; ältere Firmware kennt die neue Region nicht.

Prüfungen: Gerätekonfiguration/-editor, Freigaben, Versions-/Syncpfad,
unveränderte Mathe-Zielzahlen, Duplizieren, abgewiesene Konfigurationen sowie
idempotente Migration und Downgrade ohne Verlust bestehender Daten.
Physische Display-/Tastenabnahme siehe Firmware-Dokumentation `docs/learning.md`.
