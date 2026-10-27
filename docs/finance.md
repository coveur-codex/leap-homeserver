# Finanzen · 1.2.0

Server zuerst aktualisieren, dann Firmware 1.2.0. Migration `0019` fügt eine
standardmäßig **deaktivierte** Finanzseite und eine gemeinsame Cache-Tabelle
hinzu. Bestehende Seiten, Reihenfolge, Inhalte und Quizdaten bleiben erhalten.
Vor dem Update wie gewohnt das Datenverzeichnis sichern.

## Einrichtung

1. Einen kostenlosen persönlichen API-Key bei [Finnhub](https://finnhub.io/) anlegen.
2. `LEAP_FINANCE_PROVIDER=finnhub` und `LEAP_FINANCE_FINNHUB_KEY=...` in der
   Server-Umgebung setzen und Container neu erstellen. Die vorhandene
   `docker-compose.yml` lädt `.env` über `env_file`. Keine Keys in Git oder Firmware.
3. Gerät bearbeiten → Finanzseite aktivieren und speichern. Unter **Finanzen**
   beispielsweise `AAPL`, `MSFT`, `NVDA` hinzufügen. Symbolprüfung und Speicherung
   erfolgen sofort; auf den LEAP-Geräten erscheint die Auswahl nach dem Sync.
4. Mit ↑/↓ die Reihenfolge ändern, mit Entfernen löschen. Maximal 48 Titel pro
   Gerät, 256 unterschiedliche Titel über alle Geräte. Fehlermeldungen bleiben
   direkt beim betroffenen Symbol sichtbar. Es werden keine ETF-Ersatzwerte
   oder Beispieldaten als reale Börsenwerte ausgegeben.

## Tatsächliche Grenzen kostenloser Daten (geprüft 20.10.2026)

| Quelle | Kostenlos nutzbarer Teil | Grenzen und Entscheidung |
|---|---|---|
| [Finnhub API / Quote](https://finnhub.io/docs/api/quote), [Tarife](https://finnhub.io/pricing-stock-api-market-data) | US-Aktienkurse, Firmenprofil, Unternehmensnachrichten; persönlicher Gebrauch | Free-Tarif bis 60 Aufrufe/Minute; LEAP begrenzt konservativ auf 50. Historische OHLC-Candles sind kostenpflichtig und werden nicht angefragt. Internationale Aktien und Indizes werden im kostenlosen Adapter ausdrücklich als nicht unterstützt gemeldet. |
| [Twelve Data Tarife](https://twelvedata.com/pricing), [API](https://twelvedata.com/docs) | Basic hat 8 Credits/Minute, 800/Tag und begrenzte Märkte/Trials | Basic bezeichnet die Nutzung als „Internal non-display“. Daher **kein pauschal kostenloser Displayanbieter**. Internationaler Handel, Indexabdeckung und Anzeigerechte hängen vom Zugang ab. Optionaler Adapter, keine Kaufpflicht. |
| [Alpha Vantage](https://www.alphavantage.co/support/), [API](https://www.alphavantage.co/documentation/) | Bis 25 Aufrufe/Tag | Intraday und Indexhistorie sind Premium-Endpunkte. Deshalb keine geeignete kostenlose 5-Minuten-Quelle für diese Funktion. |

Ein kostenloser allgemeiner Zugang für deutsche und US-Aktien **plus** DAX,
S&P 500 und NASDAQ inklusive historischer Intraday-Charts konnte damit nicht
belegt werden. Die ursprünglichen Adapter verwenden dokumentierte APIs. Ab 1.3.0-beta.1
steht zusätzlich eine ausdrücklich wählbare inoffizielle Yahoo-Quelle bereit,
siehe unten. Es gibt keine HTML-Abfragen oder Sperrenumgehungen.

Finnhub liefert über `/quote` Kurs, Öffnung, Tageshoch/-tief und Originalzeitstempel.
Die Veränderung wird **gegen die Eröffnung** berechnet; `pc`, `d`, `dp` werden nicht
als Ersatz benutzt. Fehlt die Öffnung, bleibt die Veränderung unbekannt.
Der kostenlose Chart besteht aus den tatsächlich seit Beobachtungsbeginn alle
fünf Minuten empfangenen Kursständen (**Gesammelte Kurse**). Nach der Ersteinrichtung
existiert zunächst nur ein Punkt. Es gibt keine erfundene historische Kurve.
Bei einem neuen Handelstag beginnt eine neue Sammlung; bei geschlossenem Markt
bleibt der letzte verfügbare Handelstag erhalten.

Finnhub liefert Nachrichten nach konkretem Unternehmenssymbol und `related`-
Zuordnung, nicht nach einer mehrdeutigen Kürzelsuche. Nur die neueste zugeordnete
Überschrift mit Originalquelle und Originalzeit wird geliefert. Nachrichten werden
stündlich geprüft; Fehler bewahren die letzte Überschrift mit `newsStale`.

## Optionaler Anbieterwechsel

Der kleine `FinanceProvider`-Vertrag in `app/services/finance.py` kapselt Quote und
Nachrichten. Die Firmware und WebUI kennen ausschließlich das normalisierte
LEAP-Format. Für einen bereits passend lizenzierten Twelve-Data-Zugang:

```
LEAP_FINANCE_PROVIDER=twelve_data
LEAP_FINANCE_TWELVE_DATA_KEY=...
```

Dieser Adapter verwendet `/quote`, `/time_series` (5-Minuten, UTC) und bei Bedarf
`/symbol_search`. Native Symbole, ggf. `SYMBOL:EXCHANGE`, sind möglich. Für
`^GDAXI`, `^GSPC`, `^IXIC` erfolgt eine exakte Index-Namenssuche; mehrdeutige oder
fehlende Treffer werden abgelehnt. Es gibt keine geratenen Alias-Kurse. Nicht
freigeschaltete Märkte ergeben einen sichtbaren Fehler. Fehlt die Historie,
bleibt die gültige Quote mit gesammelten Punkten nutzbar. Dieser Adapter liefert
aktuell keine Nachrichten. Der konservative Basic-Creditdeckel bleibt auch bei
einem anderen Tarif bestehen. Markt-/Anzeigerechte beim Anbieter prüfen.

## Cache, Handelszeiten und Fehler

Ein Scheduler prüft fällige Titel jede Minute; erfolgreiche offene/unklare Titel
werden frühestens nach 5 Minuten erneut abgerufen, geschlossene nach 15 Minuten.
Identische Symbole werden global zusammengeführt. Schließung wird aus dem
Anbieterstatus bestimmt, einschließlich Feiertagen, nicht aus einer geratenen
Mo–Fr-Regel. Fehlt der Status, heißt es **Handel unklar**, ohne Mondsymbol. Beim
Wiederöffnen kann der geschlossene Cache daher bis zu 15 Minuten nachlaufen.

Quota-Zähler pro UTC-Tag/Minute und `Retry-After`/429-Sperren sind persistent.
Fehler werden zurückgestellt, nicht in Render- oder Geräteabrufen wiederholt.
Bei vielen Titeln verlängern sich die Abstände; nach Fälligkeit sortierte Titel
verhindern Bevorzugung derselben ersten Symbole. Für konsistente globale Limits
wie in der gelieferten Compose-Datei **einen Serverprozess** verwenden.

Erfolgreich abgefragte, geschlossene Märkte gelten nicht als technischer Fehler.
Mehr als 15 Minuten alte Quotes bei offenem Markt werden als verzögert markiert,
mehr als eine Stunde als technisch veraltet. Fehlgeschlagene Abrufe, abgelaufener
Cache (10 Minuten offen/unklar, 20 Minuten geschlossen) und über sieben Tage alte
Kurse werden als veraltet markiert. Zeitstempel werden nie auf „jetzt“ umgeschrieben.
Providerzeiten gelten in der angegebenen Börsenzeitzone einschließlich Sommerzeit.

## Geräte-API und Vorschau

`GET /api/v1/devices/{device_id}/finance` ist nur bei aktivierter Seite verfügbar.
Die Route liest ausschließlich den Cache. Schema 1 enthält `generatedAt` und eine
geordnete Liste `securities`: Symbol, Name, Währung, Original-Kurszeit, `quoteTime`,
Eröffnung/Hoch/Tief, Veränderung, Session, Zeitzone, Marktstatus, Verzögerung,
Stale-Markierung, Nachricht und bis zu 60 Chartpunkte `[epoch, price, segment]`.
Segmente werden **vor** der Reduktion bestimmt. Echte Lücken über 15 Minuten
werden nicht überzeichnet; Downsampling erzeugt keine künstlichen Lücken.
Hoch/Tief kommen aus der Quote, nicht nur aus den gesammelten Punkten.
Interne Metadaten, Rohsamples und Keys werden nicht an Geräte übertragen.

Die bestehende Displayvorschau zeigt beide Finanzansichten als Canvas in
nativen 342×142 Pixeln neben der unveränderten globalen Sidebar. Sie nutzt reale
Cache-Daten, fehlende Werte bleiben fehlend. Steuerung über die Vorschautasten
unter der Symbolliste oder Pfeiltasten/Enter bei fokussiertem Canvas.
Firmware und Vorschau verwenden dieselben Positionen, Zeitregeln und Farben;
Browser-Monospace und Hardware-Glyphen können im Schriftbild leicht abweichen.

## Prüfung

`pytest` prüft Cache-Deduplizierung, Quoten, Kursbasis, Originalzeiten,
Providerfehler, Fallback, deaktivierte Geräte, Webeditor, Vorschau und Migration.
`node tests/test_finance_preview.cjs` prüft die ausgeführte Vorschau mit künstlicher
Uhr; die Firmware prüft Navigation sowie die echte Zeichenroutine mit Displaygrenzen.
Eine echte API-Abnahme benötigt eigene passende Zugangsdaten; eine Hardwareabnahme
muss am ESP32-S3 erfolgen. Finanzdaten-Hosts müssen im Servernetz erreichbar sein:
`finnhub.io`, optional `api.twelvedata.com`.

## Cameco und ausländische Unternehmen mit US-Notierung (1.2.1)

Der Finnhub-Adapter prüft den **Handelsplatz** im Profil, nicht das Herkunftsland
des Unternehmens. Ein kanadisches Unternehmen darf beispielsweise an der NYSE
notiert sein. Bekannte US-Handelsplätze werden akzeptiert; Toronto oder europäische
Nasdaq-/Euronext-Plätze bleiben von der kostenlosen US-Konfiguration ausgeschlossen.

[Cameco](https://www.cameco.com/invest/stock-information) handelt in Toronto als
`CCO` (häufig `CCO.TO`, CAD) und an der NYSE als `CCJ` (USD). Wer Cameco über den
US-Zugang beobachten möchte, kann ausdrücklich `CCJ` konfigurieren. Das ist ein
anderer Handelsplatz mit anderer Währung; es gibt keine automatische Umbenennung
oder Umrechnung von `CCO.TO`. Für den exakten Toronto-Kurs wird ein freigeschalteter
TSX-Datenzugang benötigt, siehe [Finnhub TSX-Angebot](https://api.finnhub.io/tsx-end-of-day-level-1-data).
Die Abdeckung des eigenen API-Schlüssels muss beim tatsächlichen Abruf geprüft werden.

Die Symbolkonfiguration steht ab 1.2.1 oben bei den übrigen Geräteeinstellungen.
Symbolaktionen speichern weiterhin sofort und unabhängig vom allgemeinen
Geräteformular; dessen ungespeicherte Änderungen werden dabei nicht mitgespeichert.

**Gespeicherte Fehlermeldung nach einem Update:** Symbolfehler werden bis zu sechs
Stunden zwischengespeichert. Mit **Erneut prüfen** bei der betreffenden Zeile wird
diese Wartezeit gezielt aufgehoben. Globale API-Limits und 429-Sperren gelten
weiterhin. Bei einer weiteren Ablehnung nennt die Meldung jetzt den gemeldeten
Handelsplatz oder ein fehlendes Profil, statt pauschal einen internationalen
Markt zu vermuten.

## Kostenlose Frankfurter EUR-Kurse (1.3.0-beta.1)

Zusätzlich zur bisherigen Quelle kann je Symbol ausdrücklich der optionale
Yahoo-Adapter gewählt werden. Im Geräteeditor bieten zwei Schaltflächen:

| Eintrag | Wertpapier | WKN | Handelsplatz / Währung |
|---|---|---|---|
| `YAHOO:CJ6.F` | Cameco, ISIN CA13321L1085 | 882017 | Frankfurt / EUR |
| `YAHOO:6RJ0.F` | Rocket Lab, ISIN US7731211089 | A419CG | Frankfurt / EUR |

Die API verwendet weiterhin das konfigurierte Symbol als Identität und liefert
zusätzlich `displaySymbol` und `exchange`. Firmware und Vorschau zeigen die
kurze Notierung und den Handelsplatz. Vorhandene Einträge wie `CCO.TO`, `CCJ`
oder `RKLB` werden nicht umbenannt oder umgerechnet; nicht mehr gewünschte
Notierungen separat entfernen. US-Werte können gleichzeitig über Finnhub laufen.
Es ist kein neuer API-Key und kein Abonnement erforderlich.

**Diese Option nutzt eine inoffizielle Yahoo-JSON-Schnittstelle.** Sie hat keine
Verfügbarkeitsgarantie, und eine feste Verzögerung von höchstens 15 Minuten kann
nicht zugesagt werden. Kursseiten:
[Cameco](https://finance.yahoo.com/quote/CJ6.F/) und
[Rocket Lab](https://finance.yahoo.com/quote/6RJ0.F/).
Der kostenlose Versuch ist für persönliche Nutzung vorgesehen. Er bietet keinen
Ersatz für einen zugesicherten Marktdatenzugang. Die bisherige Beschränkung auf
rein dokumentierte APIs wird für diese ausdrücklich wählbare Quelle aufgehoben.

Nur exakt passende Symbole, Frankfurt, EUR und Europe/Berlin werden akzeptiert.
Der Adapter ruft alle fünf Minuten einen eintägigen 5-Minuten-Chart ab. Er nutzt
Originalkurs und Originalzeit sowie vorhandene Intraday-Punkte; Nullwerte bleiben
Datenlücken. Fehlt eine Kurve, werden ausschließlich tatsächlich empfangene Kurse
gesammelt. Fehlt die Eröffnung, bleibt die Veränderung unbekannt. Kursabrufe
sind auf sechs pro Minute und 600 pro UTC-Tag begrenzt. Bei HTTP 429 pausiert die
Quelle mindestens 30 Minuten. HTTP 401/403 werden als fehlender freier Zugang
angezeigt; es gibt keine Cookie-/Login-/Sperrenumgehung.

Alle Yahoo-Kurse tragen `delayed: true`. Bei Fehlern bleibt der vorherige Kurs
mit seinem Originalzeitpunkt erhalten und wird als veraltet markiert. Es gibt
keinen automatischen Wechsel zu einem USD-/CAD-Kurs oder einer anderen Börse.
Handelsstatus verwendet nur die gelieferten Sessionzeiten; ausbleibende Trades
werden nicht als Beweis für einen Feiertag behandelt.

Für den Server muss `query1.finance.yahoo.com` erreichbar sein. Tests verwenden
kontrollierte Anbieterantworten (richtiger/falscher Handelsplatz und Währung,
Kurszeit, fehlende Werte, Ausfall und Cache). Die Live-Abnahme beider konkreten
Notierungen muss am erreichbaren Server erfolgen: hinzufügen, **Erneut prüfen**,
Originalzeit/EUR/Frankfurt kontrollieren, Gerät synchronisieren und während des
deutschen Handelstags nochmals prüfen. Ein erfolgreicher Test beweist keine
langfristige API-Verfügbarkeit. Ist die freie Quelle nicht nutzbar, bleibt ein
passender kostenpflichtiger Datenzugang eine spätere Entscheidung.
