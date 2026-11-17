"""Learning uses the existing DevicePage.settings snapshot and config version."""
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, ValidationError, model_validator
from fastapi import HTTPException

Letters = Annotated[str, StringConstraints(pattern=r"^[A-ZÄÖÜ]+$", min_length=1, max_length=6)]
Word = Annotated[str, StringConstraints(pattern=r"^[A-ZÄÖÜ]+$", min_length=2, max_length=16)]


class Syllable(BaseModel):
    text: Letters
    level: Literal[1, 2, 3] = 1


class ReadingWord(BaseModel):
    word: Word
    syllables: list[Letters] = Field(min_length=2, max_length=5)
    level: Literal[1, 2, 3] = 1

    @model_validator(mode="after")
    def joined(self):
        if "".join(self.syllables) != self.word:
            raise ValueError("Silben müssen zusammen exakt das Wort ergeben")
        return self


class TrainerSettings(BaseModel):
    levels: list[Literal[1, 2, 3]] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=3)
    defaultMode: Literal[0, 1, 2] = 0
    sessionLength: Literal[10, 15] = 10
    random: bool = True
    autoSeconds: Literal[0, 5, 10, 15] = 0
    syllables: list[Syllable] = Field(default_factory=list, max_length=32)
    words: list[ReadingWord] = Field(default_factory=list, max_length=32)


def default_settings():
    return {"applications": [{"id": "math_lab", "enabled": True},
                             {"id": "syllable_trainer", "enabled": True}],
            "syllableTrainer": TrainerSettings().model_dump()}


def form_settings(previous, applications, levels, mode, length, random, seconds, syllables, words):
    try:
        if len(syllables.encode()) > 16000 or len(words.encode()) > 16000:
            raise ValueError("Eigene Inhalte sind zu groß")
        if set(applications) - {"math_lab", "syllable_trainer"}:
            raise ValueError("Unbekannte Lernanwendung")
        trainer = TrainerSettings(levels=levels, defaultMode=mode, sessionLength=length,
                                  random=random, autoSeconds=seconds,
                                  syllables=json.loads(syllables), words=json.loads(words))
        result = {**previous,
                  "applications": [{"id": app, "enabled": app in applications}
                                   for app in ("math_lab", "syllable_trainer")],
                  "syllableTrainer": trainer.model_dump()}
        return result
    except (ValueError, TypeError, ValidationError) as error:
        raise HTTPException(422, f"Ungültige Lernwelt-Einstellungen: {error}") from error
