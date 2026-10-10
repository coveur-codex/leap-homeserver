"""Stable IDs for games compiled into the LEAP firmware."""
GAME_REGISTRY = (
    ("tamagotchi", "Mein Haustier"),
    ("snake", "Snake"),
    ("hot_potato", "Heiße Kartoffel"),
    ("simon_motion", "Simon"),
    ("tilt_maze", "Kipp-Labyrinth"),
    ("connect_four", "Vier Gewinnt"),
    ("kitchen", "Meine Küche"),
    ("crab_journey", "Krabbenreise"),
    ("dragon_run", "Dragon Run"),
)
# Preserve the games previously shown by the server plus the firmware's kitchen.
DEFAULT_GAMES = [game_id for game_id, _ in GAME_REGISTRY]
