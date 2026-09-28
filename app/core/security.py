import ipaddress, socket
from urllib.parse import urlparse
from .config import settings

def validate_external_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Nur gültige HTTP/HTTPS-URLs sind erlaubt")
    if parsed.username or parsed.password:
        raise ValueError("URLs mit Zugangsdaten sind nicht erlaubt")
    for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        ip = ipaddress.ip_address(info[4][0])
        if not settings.allow_private_feeds and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
            raise ValueError("Lokale/private Ziele sind blockiert")
    return url
