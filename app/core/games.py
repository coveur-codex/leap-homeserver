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
    ("dragon_run", "Drachenrennen"),
    ("fall_blocks", "Fallblöcke"),
)
# Fallblöcke is enabled explicitly in the device editor.
DEFAULT_GAMES = [game_id for game_id, _ in GAME_REGISTRY if game_id != "fall_blocks"]
