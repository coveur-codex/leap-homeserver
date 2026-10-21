"""Validated, bounded input shared by the device editor and API."""
import re
from urllib.parse import urlsplit

DEFAULT_SERVER = "http://ndk.tstromi.de:8080"

def server_url(value):
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
    except ValueError:
        raise ValueError("Ungültige Serveradresse") from None
    if (len(value.encode()) > 256 or not value.isascii() or any(c.isspace() or ord(c)<32 for c in value)
        or parsed.scheme not in {"http", "https"} or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path or "\\" in value):
        raise ValueError("Serveradresse als http(s)://Hostname[:Port] ohne Pfad oder Zugangsdaten angeben")
    return value

def target_numbers(value):
    if len(value) > 1024:
        raise ValueError("Zahlenliste ist zu lang")
    result = set()
    for token in value.split(","):
        match = re.fullmatch(r"\s*(\d{1,3})(?:\s*-\s*(\d{1,3}))?\s*", token)
        if not match:
            raise ValueError("Zielzahlen als Liste oder Bereich angeben, zum Beispiel 9,10 oder 3-15")
        lo = int(match[1]); hi = int(match[2] or lo)
        if not 1 <= lo <= hi <= 100:
            raise ValueError("Zielzahlen müssen zwischen 1 und 100 liegen; Bereiche aufsteigend angeben")
        result.update(range(lo, hi+1))
    return sorted(result)

def wifi_profile(ssid, password):
    if not ssid or len(ssid.encode()) > 32 or any(ord(c)<32 for c in ssid):
        raise ValueError("WLAN-Name muss 1–32 UTF-8-Bytes enthalten")
    raw = password.encode()
    if password and not (8 <= len(raw) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", password)):
        raise ValueError("WLAN-Passwort: leer für offene Netze, 8–63 Bytes oder 64 Hex-Zeichen")
    if any(ord(c)<32 for c in password):
        raise ValueError("WLAN-Passwort enthält Steuerzeichen")
    return {"ssid":ssid, "password":password}
