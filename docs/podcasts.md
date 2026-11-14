# Podcasts Stufe 1 · Homeserver 1.7.0

Zuerst Homeserver 1.7.0 mit Migration **0025** installieren, danach Firmware
1.7.0. Bestehende Geräte erhalten eine deaktivierte Podcast-Seite und leere
Freigaben. Radio-Konfiguration, Seitensortierung und andere Inhalte bleiben erhalten.

Unter **Podcasts** einen Namen, eine HTTP(S)-RSS-/Atom-URL und eine Position
angeben. Hinzufügen prüft den Feed sofort; **Aktualisieren** startet einen
manuellen Abruf. Aktivierung, Bearbeiten, Sortierung, letzte erfolgreiche
Aktualisierung, Fehlermeldung und MP3-Anzahl stehen in derselben Tabelle.
**Episoden anzeigen** zeigt auch nicht unterstützte und entfallene Einträge.
Unter **Geräte → Podcasts** die Kanäle freigeben und oben die Seite aktivieren.
Nur zentral aktive und ausdrücklich freigegebene Kanäle gelangen ins Gerät.
Änderungen erhöhen die Konfigurationsversion der betroffenen Geräte.

## Daten und RSS

- `podcasts`: zentrale Quellen, Sortierung und Aktualisierungsdiagnose.
- `podcast_episodes`: Titel, bereinigte Beschreibung, Datum, Dauer, Enclosure-URL,
  Format und Verfügbarkeit. Geräte erhalten ausschließlich verfügbare MP3s.
- Episoden-ID: SHA-256 aus Podcast-ID und RSS-GUID/Atom-ID; ohne GUID wird die
  Enclosure-URL verwendet. Geänderte URLs mit unveränderter GUID behalten ihren
  Fortschritt. Ohne GUID kann ein URL-Wechsel eine neue Episode erzeugen.
- Doppelte GUIDs/Enclosures werden beim Import übersprungen. Entfallene Folgen
  werden als nicht verfügbar markiert; Fortschritt bleibt erhalten. Fehlerhafte
  Abrufe ersetzen den letzten gültigen Katalog nicht.
- Aktualisierung alle drei Stunden, Prüfung fälliger Quellen jede Minute.
  HTTP-Timeout aus der bestehenden Konfiguration, höchstens fünf Weiterleitungen,
  maximal 8 MiB Feed-Daten. Die bestehende Policy für private Feed-Ziele wird auf
  jede Weiterleitung angewendet. Keine Transkodierung und kein Audio-Download.
- Die Feedliste bestimmt den verfügbaren Umfang. Alle darin angebotenen MP3s sind
  über Pagination erreichbar; es gibt kein Limit auf die letzten 10/20 Folgen.

## Geräte-API

Alle Pfade beginnen mit `/api/v1/devices/{device_id}/podcasts`.
Geräte-ID und Aktivierung werden wie bei den bestehenden Geräte-APIs geprüft;
zusätzlich prüft jeder Abruf/Upload die Seite, zentrale Aktivierung und Freigabe.
Es wird dasselbe Vertrauensmodell im Heimnetz verwendet, keine neue Anmeldung.

| Methode / Pfad | Antwort / Zweck |
|---|---|
| `GET /resume` | Letzte weiterhin verfügbare und freigegebene Episode oder `episode: null`; dazu Listenoffset |
| `GET /{id}/episodes?offset=0&limit=12` | `podcastId`, `offset`, `total`, `nextOffset`, `episodes`; maximal 20 je Anfrage |
| `GET /{id}/episodes/{episode_id}` | Frische URL/Metadaten und absoluter Listenoffset |
| `GET /{id}/next?after={episode_id}` | Nächste nicht abgeschlossene Folge desselben Kanals; nach Listenende Suche ab Anfang, andernfalls `null` |
| `POST /progress` | Idempotenter Fortschrittsupload |

Konfiguration: `config.podcasts = [{id, name, episodeCount}]`, unabhängig von
Episodenlisten und Wiedergabedaten. Sortierung: Veröffentlichungsdatum absteigend,
bei gleichem Datum stabile Episoden-ID absteigend. Bereits gehörte Folgen bleiben sichtbar.
Für Vorige/Nächste während der Wiedergabe kann die Listenanfrage `anchor={episode_id}`
und eine relative `direction` angeben. Der Server bestimmt den aktuellen Offset und
liefert `selectedOffset`; neue RSS-Einträge verschieben dadurch nicht den gewählten
Nachbarn. Ohne Anker bleibt normale Offset-Pagination erhalten.

Ein Fortschrittsupload enthält `podcastId`, `episodeId`, `position` und `duration`
in Sekunden, `status` (`unheard`, `partial`, `completed`), eine steigende
64-Bit-`revision` sowie `naturalEnd`. Nur ein reguläres Ende darf
`completed` mit `naturalEnd: true` melden. Der Server speichert je Gerät/Episode
Position, Dauer, Zustand, Revision und Aktualisierungszeit. Wiederholte und ältere
Revisionen überschreiben keinen neueren Stand. Der letzte Kanal/die letzte Folge
werden separat am Gerät gespeichert; nur die neueste Revision aktualisiert sie.

Firmware speichert etwa alle 20 Sekunden bei verändertem Fortschritt, bei Pause,
Folgenwechsel und Seitenende in einem atomar ersetzten lokalen Journal und lädt
anschließend hoch. Wiederholungen nach Neustart sind ungefährlich. Der lokale
Cache hält bis zu 128 Fortschrittsstände und 32 Metadaten-Dateien; bestätigte alte
Stände können verdrängt werden. Serverfortschritt und Episodenlisten sind nicht
auf diese Cachegröße begrenzt. Bei langem Offline-Betrieb bleiben unbestätigte
Stände erhalten; ein voller Cache wird am Gerät angezeigt.

Spulen und Wiedergabegrenzen: siehe Firmware-Dokumentation `docs/podcasts.md`.
Der Homeserver prüft Enclosure-Metadaten; die tatsächlichen MP3-Frames und die
Erreichbarkeit des Audioanbieters prüft der Decoder auf dem ESP32.
