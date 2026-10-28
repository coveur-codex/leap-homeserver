# 1.4.1 – OTA-Dateiversion verbindlich prüfen

- Upload prüft eingebettete Dateiversion gegen die Release-Version.
  Unmarkierte, mehrdeutige und falsch beschriftete Dateien werden abgewiesen.
- Prüfung gilt auch für vorhandene Releases, neue Angebote, Downloads aus alten
  Sync-Plänen, Stable-Freigabe und Wiederfreigabe. Die Firmware-Seite zeigt den Grund.
- Für neue Releases universelle Firmware ab 1.4.1 mit Build-Kennzeichnung verwenden;
  bestehende Geräte können diese weiterhin per OTA erhalten. Keine DB-Migration.

# 1.4.0 – Größeres Snake-Spielfeld und Spielestatus

- Kooperatives Snake verwendet jetzt 53×16 Felder. Veraltete Geräte erhalten
  beim Beitritt einen Firmware-Updatehinweis und belegen keinen Lobbyplatz.
- Neuer Reiter Spielestatus: Lobby, Countdown, laufende Partie, Teilnehmer,
  Verbindungen, Restzeit, Teamziel und Ergebnis; automatische Aktualisierung.
- Gemeinsame, erweiterbare Status-Registry und JSON-Schnittstelle für weitere
  serververwaltete Spiele. Statusleser verändern die laufende Simulation nicht.
- Zum Umstieg zuerst Firmware 1.4.0, danach den Homeserver aktualisieren.
- Keine neuen Abhängigkeiten oder Datenbankmigrationen.

# 1.4.0-beta.1 – Kooperatives Multiplayer-Snake

- Autoritatives kooperatives Snake für 2–4 Geräte über vorhandene WebSockets:
  automatische 10s-Lobby, 3–2–1, 120s Spielzeit, gemeinsame Früchte/Punkte,
  sichere simultane Kollisionen und Wiedereinstieg nach drei Sekunden.
- Wiederverbindung mit Sessionkennung, Eingabesequenzen und vollständigen
  Zuständen; langsame Empfänger blockieren keine anderen Geräte.
- Automatisches gemeinsames `game-avatars` aus `pagestatics/games.png`,
  80×80 transparent, Hashreuse und regulärer Asset-Sync.
- Betrieb mit einem Uvicorn-Worker. Keine Datenbankmigration oder neue Abhängigkeit.
- Protokoll und noch erforderliche Hardware-Abnahme: `docs/snake-multiplayer.md`.

# 1.3.0-beta.1 – WLAN, Zahlenzerlegung und deutsche EUR-Kurse

- Geräteeditor: Serveradresse und vier WLAN-Profile je Gerät mit separater
  Revision. Die Geräte-API liefert Zugangsdaten getrennt vom Inhalts-Snapshot;
  gespeicherte Passwörter werden im Formular nicht wieder angezeigt.
- Mathe-Labor: konfigurierbare Zielzahlen als Liste oder Bereich (1–100) für
  „Fehlenden Teil finden“, beispielsweise 9,10 oder 3-15. Migration 0020 erhält
  vorhandene Geräte und Inhalte.
- Optionaler kostenloser Yahoo-Adapter für Cameco (CJ6.F, WKN 882017) und
  Rocket Lab (6RJ0.F, WKN A419CG), jeweils Frankfurt/EUR. US-Kurse bleiben
  unabhängig konfigurierbar. Keine kostenpflichtigen Dienste werden gebucht.
- Yahoo nutzt eine inoffizielle Schnittstelle ohne Verfügbarkeits- oder feste
  Verzögerungsgarantie. Kurszeit, Währung und Handelsplatz werden geprüft;
  Ausfälle erhalten den vorherigen Stand mit einer Veraltet-Markierung.
- 305 Servertests und die Finanzvorschau bestanden. Live-Kursprüfung und
  Hardware-Abnahme mit Firmware 1.3.0-beta.1 stehen noch aus.
