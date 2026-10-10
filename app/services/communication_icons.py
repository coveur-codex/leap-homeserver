"""Fixed child-friendly icon IDs shared with firmware 1.0.6.

Icons use the existing templateId envelope and relay snapshot. No device can
inject arbitrary text, symbols or sender names. No DB migration is necessary.
"""
import json
from pathlib import Path

ICONS = {row["id"]: row for row in json.loads(
    (Path(__file__).resolve().parents[1] / "defaults/communication-icons.json").read_text())}
