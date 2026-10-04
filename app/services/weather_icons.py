"""Weather-code labels and vector illustrations built from simple SVG primitives."""
from markupsafe import Markup


def weather_kind(code):
    groups = {
        "clear": (0,), "mostly-clear": (1,), "partly-cloudy": (2,), "overcast": (3,),
        "fog": (45, 48), "drizzle": (51, 53, 55), "freezing-rain": (56, 57, 66, 67),
        "rain": (61, 63, 65), "snow": (71, 73, 75, 77), "showers": (80, 81, 82),
        "snow-showers": (85, 86), "thunder": (95,), "hail": (96, 99),
    }
    return next((kind for kind, codes in groups.items() if code in codes), "unknown")


def weather_label(code, day=True):
    labels = {"clear": "Sonnig" if day else "Klar", "mostly-clear": "Meist sonnig" if day else "Meist klar",
              "partly-cloudy": "Wolkig", "overcast": "Bedeckt", "fog": "Nebel", "drizzle": "Nieselregen",
              "freezing-rain": "Eisregen", "rain": "Regen", "snow": "Schnee", "showers": "Regenschauer",
              "snow-showers": "Schneeschauer", "thunder": "Gewitter", "hail": "Gewitter/Hagel", "unknown": "Wetter unbekannt"}
    return labels[weather_kind(code)]


def weather_icon(code, day=True):
    kind = weather_kind(code)
    shapes = []
    def add(shape): shapes.append(shape)
    if kind == "unknown":
        add('<circle cx="32" cy="30" r="18" fill="none" stroke="#79958d" stroke-width="2"/><path d="M25 22L32 19L39 24L32 32V36M32 41V43" fill="none" stroke="#49675b" stroke-width="3"/>')
    else:
        if kind in ("clear", "mostly-clear", "partly-cloudy", "showers", "snow-showers"):
            cx, cy = (32, 30) if kind == "clear" else (21, 21)
            if day:
                import math
                for ray in range(8):
                    a = ray * math.pi / 4
                    add(f'<path d="M{cx + 15 * math.cos(a):.2f} {cy + 15 * math.sin(a):.2f}L{cx + 20 * math.cos(a):.2f} {cy + 20 * math.sin(a):.2f}" stroke="#eeb035" stroke-width="2" stroke-linecap="round"/>')
                add(f'<circle cx="{cx}" cy="{cy}" r="12" fill="#f7c344" stroke="#eda42b" stroke-width="2"/><circle cx="{cx-3}" cy="{cy-3}" r="3" fill="#fff1b2"/>')
            else:
                # A crescent path stays transparent against any card background.
                add(f'<path d="M{cx+6} {cy-10}A12 12 0 1 0 {cx+10} {cy+7}A11 11 0 0 1 {cx+6} {cy-10}" fill="#ecd681"/>')
                add('<path d="M48 7V13M45 10H51" stroke="#b1a45a" stroke-width="2"/><circle cx="56" cy="20" r="1.5" fill="#b1a45a"/>')
        if kind != "clear":
            fill = "#94a3b8" if kind in ("overcast", "thunder", "hail") else "#e9f1f5"
            dy = 9 if kind == "mostly-clear" else 0
            add(f'<g transform="translate(0 {dy})"><path d="M17 43C4 43 4 23 17 22C22 6 42 8 43 20C60 18 62 43 44 43Z" fill="{fill}" stroke="#6e899e" stroke-width="2"/><path d="M18 39H44" stroke="#bacbd7" stroke-width="2"/><circle cx="26" cy="20" r="3" fill="#ffffff" fill-opacity=".5"/></g>')
        if kind == "fog":
            add('<path d="M7 47H42M19 52H57M9 57H43" stroke="#8ca5a6" stroke-width="2" stroke-linecap="round"/>')
        elif kind == "drizzle":
            for x in (18, 30, 42):
                add(f'<circle cx="{x}" cy="49" r="1.5" fill="#3bafdb"/><circle cx="{x-2}" cy="56" r="1.5" fill="#3bafdb"/>')
        elif kind in ("rain", "showers", "freezing-rain"):
            add('<path d="M18 47L14 55M31 47L27 55M44 47L40 55" stroke="#3bafdb" stroke-width="2.5" stroke-linecap="round"/>')
            if code in (65, 82): add('<path d="M25 56L23 61M39 56L37 61" stroke="#3bafdb" stroke-width="2"/>')
        if kind in ("snow", "snow-showers", "freezing-rain"):
            for x, y in (((49, 58),) if kind == "freezing-rain" else ((17, 51), (32, 56), (47, 50))):
                add(f'<path d="M{x-4} {y}H{x+4}M{x-2} {y-4}L{x+2} {y+4}M{x+2} {y-4}L{x-2} {y+4}" stroke="#5cbbd4" stroke-width="1.5"/>')
        if kind in ("thunder", "hail"):
            add('<path d="M30 43L24 54L34 51L27 62L38 49H31L36 43Z" fill="#f5c534"/>')
            if kind == "hail": add('<circle cx="16" cy="51" r="3" fill="#c4eefa" stroke="#67abc3"/><circle cx="45" cy="55" r="3" fill="#c4eefa" stroke="#67abc3"/>')
            else: add('<path d="M17 47L13 56M47 47L43 56" stroke="#3bafdb" stroke-width="2"/>')
    # Only fixed geometry and a known condition key enter this markup; no provider strings.
    return Markup(f'<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" data-weather-icon="{kind}">{"".join(shapes)}</svg>')
