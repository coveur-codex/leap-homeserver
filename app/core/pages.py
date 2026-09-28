from dataclasses import dataclass
@dataclass(frozen=True)
class PageDefinition:
    id: str
    title: str
    configurable: bool = True
    implemented: bool = True
PAGE_REGISTRY = [
    PageDefinition("home", "Home"), PageDefinition("news", "News"),
    PageDefinition("weather", "Wetter"), PageDefinition("quiz", "Quiz"),
    PageDefinition("games", "Spiele"), PageDefinition("aircraft", "Flugzeuge", implemented=False),
    PageDefinition("knowledge", "Wissen", implemented=False), PageDefinition("settings", "Einstellungen"),
]
