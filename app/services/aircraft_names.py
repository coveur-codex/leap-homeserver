"""Small offline display catalog. Unknown codes stay available in the API."""
AIRCRAFT_TYPES = {
    "B738": "Boeing 737-800", "B737": "Boeing 737-700", "B739": "Boeing 737-900",
    "B38M": "Boeing 737 MAX 8", "B39M": "Boeing 737 MAX 9", "B736": "Boeing 737-600",
    "B744": "Boeing 747-400", "B748": "Boeing 747-8", "B752": "Boeing 757-200",
    "B753": "Boeing 757-300", "B763": "Boeing 767-300", "B772": "Boeing 777-200",
    "B77L": "Boeing 777-200LR", "B77W": "Boeing 777-300ER", "B788": "Boeing 787-8",
    "B789": "Boeing 787-9", "B78X": "Boeing 787-10",
    "A318": "Airbus A318", "A319": "Airbus A319", "A320": "Airbus A320",
    "A321": "Airbus A321", "A19N": "Airbus A319neo", "A20N": "Airbus A320neo",
    "A21N": "Airbus A321neo", "A332": "Airbus A330-200", "A333": "Airbus A330-300",
    "A338": "Airbus A330-800neo", "A339": "Airbus A330-900neo",
    "A343": "Airbus A340-300", "A346": "Airbus A340-600", "A359": "Airbus A350-900",
    "A35K": "Airbus A350-1000", "A388": "Airbus A380-800",
    "BCS1": "Airbus A220-100", "BCS3": "Airbus A220-300",
    "E170": "Embraer 170", "E75L": "Embraer 175", "E75S": "Embraer 175",
    "E190": "Embraer 190", "E195": "Embraer 195", "E290": "Embraer 190-E2",
    "E295": "Embraer 195-E2", "CRJ9": "Bombardier CRJ900", "CRJ7": "Bombardier CRJ700",
    "AT72": "ATR 72", "AT76": "ATR 72-600", "DH8D": "De Havilland Dash 8-400",
    "C172": "Cessna 172", "C152": "Cessna 152", "PC12": "Pilatus PC-12",
}
AIRPORTS = {
    "CGN": "Köln/Bonn", "EDDK": "Köln/Bonn", "DUS": "Düsseldorf", "EDDL": "Düsseldorf",
    "FRA": "Frankfurt am Main", "EDDF": "Frankfurt am Main", "MUC": "München", "EDDM": "München",
    "BER": "Berlin Brandenburg", "EDDB": "Berlin Brandenburg", "HAM": "Hamburg", "EDDH": "Hamburg",
    "STR": "Stuttgart", "EDDS": "Stuttgart", "HAJ": "Hannover", "EDDV": "Hannover",
    "LEJ": "Leipzig/Halle", "EDDP": "Leipzig/Halle", "NUE": "Nürnberg", "EDDN": "Nürnberg",
    "VIE": "Wien", "LOWW": "Wien", "ZRH": "Zürich", "LSZH": "Zürich",
    "AMS": "Amsterdam Schiphol", "EHAM": "Amsterdam Schiphol", "LHR": "London Heathrow",
    "EGLL": "London Heathrow", "CDG": "Paris Charles de Gaulle", "LFPG": "Paris Charles de Gaulle",
    "PMI": "Palma de Mallorca", "LEPA": "Palma de Mallorca", "JFK": "New York John F. Kennedy",
    "KJFK": "New York John F. Kennedy", "IST": "Istanbul", "LTFM": "Istanbul",
}


def airport_name(value):
    if isinstance(value, dict):
        name = value.get("name")
        code = value.get("iata") or value.get("icao") or value.get("code")
        return name or AIRPORTS.get(str(code).upper(), code)
    if isinstance(value, str) and value.strip():
        value = value.strip()
        return AIRPORTS.get(value.upper(), value)
    return None
