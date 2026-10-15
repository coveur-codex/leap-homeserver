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
Verfügbarkeit und Bildinhalt sind nicht garantiert. HTTPS-Weiterleitungen werden
nur zu LoremFlickr, live.staticflickr.com oder farmN.staticflickr.com akzeptiert.
Ändert der Dienst seine Hosts oder Formate, bleibt das letzte Gerätebild bestehen.

Die ESP32-Firmware benötigt physische Prüfungen über 5 und 30 Minuten ohne Eingabe,
mit mehreren Bildwechseln, allen vier Musikprofilen, Moduswechsel/Rückkehr,
WLAN-Unterbrechung und Reconnect. Die dafür nötige Hardware ist hier nicht verbunden.
PSRAM-Obergrenze für zwei Foto-RGB565-Puffer: 243.104 Bytes zusätzlich zum bestehenden
Canvas. Audio nutzt acht Stimmen und einen 6-KiB-Stack im vorhandenen Audio-Task.
CPU-Last, Audioqualität und tatsächliche Display-Framerate sind am Gerät zu messen.
