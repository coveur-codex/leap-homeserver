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
    ("rangierwerk", "Rangierwerk"),
    ("minesweeper", "Minesweeper"),
    ("breakout", "Breakout"),
    ("pfuetzenpost", "Pfützenpost"),
    ("dice", "Würfeln"),
)
# These games are enabled explicitly in the device editor.
OPT_IN_GAMES = {"fall_blocks", "rangierwerk", "minesweeper", "breakout", "pfuetzenpost", "dice"}
DEFAULT_GAMES = [game_id for game_id, _ in GAME_REGISTRY if game_id not in OPT_IN_GAMES]
