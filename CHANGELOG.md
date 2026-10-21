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
