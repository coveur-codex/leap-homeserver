# LEAP 1.1.2: Anzeige, eigene Fotos und Chatporträts

Zuerst Homeserver 1.1.2 mit `alembic upgrade head` (Migration 0017), danach Firmware
1.1.2 und den normalen Geräte-Sync installieren. Bestehende Freigaben bleiben erhalten.

## Eigene Chill-Bilder

Im Geräteeditor unter Chill die Bilderbibliothek öffnen, JPEG/PNG/WebP hochladen
oder vorhandene Fotos auswählen. Uploads werden dem Album hinzugefügt; Speichern
aktiviert die eigene Szene. Die Szenenauswahl erlaubt weiterhin den Wechsel zu
LoremFlickr, Feuer, Schnee oder Weltall. Es ist jeweils eine Szene aktiv.

Dateien: höchstens 8 MiB und 20 Megapixel je Upload, 1–24 Bilder je Album. Der Server
speichert nur ein ausgerichtetes, auf 428×142 zugeschnittenes Baseline-JPEG mit
Qualität 82, optimierter Kompression und ohne EXIF. Die gemeinsame Bibliothek hält
jedes Ergebnis nur einmal anhand seines SHA256-Hashes. Keine Original-Uploads oder
zusätzlichen Vorschaukopien. Dateinamen bleiben ausschließlich als Anzeigenamen in
der Datenbank. Ein dupliziertes Gerät erhält ein eigenes Paket und kann seine
Auswahl unabhängig ändern. Andere Geräte bekommen ausschließlich ihre eigene Auswahl.

`chill_photos` speichert Bildname und Größe; das Gerät hält `chill_photos` und die
Paket-ID `chill_album_id`. Das Album wird als bestehendes Chill-Paket mit `scene:
album`, `photos` und `minFirmware: 1.1.2` veröffentlicht. Pro Foto gibt es einen
Hash-Dateiverweis. Die bestehenden unveränderlichen Assetversionen bleiben
für laufende Downloads erhalten; Archivversionen verwenden dieselben Bildblobs.
Das Gerät räumt ersetzte Inhalte über den vorhandenen bestätigten Sync auf.

Die Firmware nutzt den bestehenden Fotoarbeiter, Bildabstand 30–300 Sekunden,
Musik und Überblendungen. Dekodierte Bilder benötigen höchstens zwei RGB565-Puffer,
keinen Puffer je Albumfoto. Lokale Alben erzeugen keine externen HTTP-Anfragen.

## Nachrichtenavatare

`communication-avatars` ist ein geschütztes, automatisch verwaltetes Common-Paket.
Die Quelle pro Avatar ist bevorzugt `data/pet/pagestatics/communication.png`,
auch innerhalb eines zusätzlichen Archivordners. Falls nicht vorhanden, werden
explizite `pageStatics.communication`, PNG-Preview oder Idle-PNG verwendet.
Die Bilder werden unter Wahrung des Seitenverhältnisses in ein transparentes
48×48-PNG eingepasst. Gleiche Ergebnisse teilen denselben Inhalts-Hash.

Jede neue Relay-Nachricht speichert `avatar_image` und sendet `avatarImage` über
HTTP und WebSocket. Wiederholte Sendungen behalten den ursprünglichen Snapshot,
auch nach einer Avataränderung. Das gemeinsame Paket enthält die aktuellen
Porträts sowie noch in der siebentägigen Nachrichtenhistorie referenzierte Bilder.
Unveränderte Quell-Hashes erzeugen keine neue Paketversion. Ein fehlendes Porträt
beeinträchtigt die Nachricht nicht: Die Firmware zeigt einen gezeichneten Platzhalter.

Der Chat zeichnet rechts bei x=372, y=6 ein 48px-Porträt; Namen und Text bleiben
links davon. Die bisherige 86px-Sidebar mit dem eigenen Avatar bleibt erhalten.

## Anzeige und Abnahme

Mathe-Labor verwendet die Geräteakzentfarbe, mit hellem/dunklem Auswahltext je
Helligkeit. Dunkelviolette Augen ersetzen Gelb auf weißem Würfelgrund.
Die Firmwareüberschriften verwenden Helvetica Bold 8: 8px hohe Großbuchstaben,
10px mit Umlaut, proportional und fett; News, Flugzeugkennung und Quiz verwenden
weiterhin denselben gemeinsamen Umbruch. Auch die Webvorschau nutzt flachere,
fette Überschriften.

Am Gerät prüfen: Lesbarkeit mit hellen/dunklen Akzentfarben, News-/Quiz-Umbrüche,
48px-Avatare bei Text und Einzel-Icons, verzögert eintreffendes Porträtpaket,
Album nach Neustart ohne WLAN, Szenenwechsel und Übergänge zwischen mehreren Bildern.
