# Abnahme 1.1.0

Automatisiert geprüft werden Keyword-Validierung, pro Gerät gespeicherte Themen
und Config-Version-Sync, Szenenauswahl, Mindestfirmware, Displayvorschau-Markup,
Redirect-Validierung, frische Random-Parameter, Typ-/Größenlimits, Timeouts,
Bildkonvertierung, Download-Zusammenfassung/Backoff sowie begrenzter persistenter
Cache. Externe Dienste werden gemockt. Die vollständige bestehende Server- und
JavaScript-Vorschau-Suite ergänzt diese Tests. Migrationsprüfungen decken frische
und bestehende Datenbanken einschließlich erhaltener Quizdaten ab.

Nicht live geprüft: LoremFlickr antwortet aus dieser Arbeitsumgebung wegen der
Netzwerkfreigabe mit HTTP 403. Vor Release den echten Dienst einschließlich
Weiterleitungskette, zufälliger Bildauswahl und mehrerer Themen testen. Externe
Verfügbarkeit und Bildinhalt sind nicht garantiert. HTTPS-Weiterleitungen werden je Quelle nur zu deren festen Hosts akzeptiert:
LoremFlickr, live.staticflickr.com oder farmN.staticflickr.com für die Hauptquelle,
picsum.photos oder fastly.picsum.photos für den Ersatzdienst.
Ändert der Dienst seine Hosts oder Formate, bleibt das letzte Gerätebild bestehen.

Die ESP32-Firmware benötigt physische Prüfungen über 5 und 30 Minuten ohne Eingabe,
mit mehreren Bildwechseln, allen vier Musikprofilen, Moduswechsel/Rückkehr,
WLAN-Unterbrechung und Reconnect. Die dafür nötige Hardware ist hier nicht verbunden.
PSRAM-Obergrenze für zwei Foto-RGB565-Puffer: 243.104 Bytes zusätzlich zum bestehenden
Canvas. Audio nutzt acht Stimmen und einen 6-KiB-Stack im vorhandenen Audio-Task.
CPU-Last, Audioqualität und tatsächliche Display-Framerate sind am Gerät zu messen.

## Diagnose bei HTTP 503 am Gerät

Ein `503` auf `/api/v1/devices/.../chill/photo` kommt vom Foto-Proxy. Ein späterer
`200` ohne Pfad im seriellen Log kann etwa der reguläre Flugradarabruf sein.
Der Homeserver protokolliert jeden fehlgeschlagenen Foto-Versuch mit
`chill_photo_failed device=... stage=download|decode|cache error=... reason=...`.
Darin stehen beispielsweise der externe HTTP-Status, DNS-/TLS-Fehler, ein
abgelehnter Weiterleitungshost, der Bildtyp oder ein Schreibfehler. Fehlgeschlagene
Wiederholungen innerhalb der vorhandenen Wartezeit erzeugen keine weiteren Warnungen.
API und Vorschau liefern weiterhin die generische 503-Antwort.

Logs anzeigen: `docker logs --since 10m leap-homeserver`.
Zum isolierten Test des laufenden Downloaders, auch auf älteren Versionen:

```sh
docker exec leap-homeserver python -c 'import asyncio; from app.services.chill import download; print("Bildbytes:", len(asyncio.run(download("nature"))))'
```

Der Test verändert keine Einstellungen und gibt bei Fehlern die ursprüngliche
Python-Ausnahme aus. Die konkrete Ursache muss anhand dieser Ausgabe festgestellt
werden; ein 503 allein belegt weder einen Displayfehler noch einen bestimmten
Fehler des externen Bilddienstes.


## Ausbleibende Antwort des Bilddienstes

Ein `httpx.ReadTimeout` beim Empfang der HTTP-Antwortheader bedeutet, dass der
angefragte Dienst innerhalb der Wartezeit keine Header geliefert hat. Auch ein
60-Sekunden-Test ohne Weiterleitungen kann diesen Zustand bestätigen. Das belegt
noch nicht, ob der Dienst allgemein ausfällt oder die Verbindung aus dem lokalen
Netz betroffen ist; Browserzugriff im WLAN und über Mobilfunk helfen bei der
Unterscheidung. Eine längere Wartezeit allein garantiert kein Bild.

Die Serveranpassung trennt deshalb den kurzen Geräteaufruf vom längeren, begrenzten
Hintergrundabruf. Bereits erfolgreiche Bilder bleiben erhalten. Solange keine der
beiden Quellen ein gültiges Bild liefert, bleibt die erste Bildanzeige ohne Cache
schwarz; Musik und Bedienung laufen weiter. Ein Firmware-Update ist für diese
Anpassung nicht erforderlich.


## Verfügbarkeit durch Picsum-Fallback

LoremFlickr hat ein Abrufbudget von acht Sekunden. Bei Timeout, HTTP-/Formatfehler
oder fehlgeschlagener Bilddecodierung folgt automatisch Picsum mit einem Budget
von 20 Sekunden. Die fünfminütige Wartezeit für die Hauptquelle gilt serverweit,
sodass weitere Bilder und Geräte bei einer Störung direkt Picsum verwenden.
Ein Abruf nach Ablauf der Wartezeit prüft LoremFlickr erneut. Funktioniert es
wieder, werden die gespeicherten Themen wieder angewendet. Picsum liefert zufällige
Fotografien und kann das Keyword nicht berücksichtigen; das steht auch am Themenfeld.

Automatisiert geprüft: Fallback nach Timeout/HTTP-Fehler/defekten Bilddaten,
begrenzter Fallback-Timeout, Wartezeit und Rückkehr zur Hauptquelle, zufällige
Picsum-URLs und deren echte Redirect-Form mit einem HTTPX-Mock, getrennte Hostlisten
sowie Erhalt des letzten Bildes beim Ausfall beider Quellen. Eine Live-Abfrage von
Picsum ist aus der Entwicklungsumgebung aufgrund der ausgehenden Netzwerkfreigabe
nicht möglich. Die Erreichbarkeit im tatsächlichen Heimnetz ist gesondert zu prüfen.
