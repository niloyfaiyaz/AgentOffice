"""Project-name normalization. Two names are the same project name when they match after
Unicode NFKC normalization, trimming, collapsing internal whitespace and case-folding
("TravelPoll", " travelpoll ", "ＴｒａｖｅｌＰｏｌｌ" are duplicates). Uniqueness is enforced by a
partial unique index on ``projects.name_key`` over active (non-archived) user projects; in a
future multi-user deployment the index would include the owner id."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def display_name(name: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", name or "")).strip()


def name_key(name: str) -> str:
    return display_name(name).casefold()
