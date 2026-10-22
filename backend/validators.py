"""
Shared validation / normalization helpers.

Room names: to stop duplicate rooms like "503 B", "B 503", "503B" and
"b-503" all being entered as separate rooms, every room name is forced
into one canonical form: <digits> or <digits>-<LETTER>, e.g. "503-B" or
"301". Any of the equivalent spellings above normalize to the same
string, and the DB has a uniqueness constraint on Room.name so a true
duplicate is rejected outright rather than silently re-created.
"""
import re

_ROOM_RE = re.compile(r"^\s*([A-Za-z]?)[\s\-]*?(\d{1,4})[\s\-]*?([A-Za-z]?)\s*$")


class RoomNameError(ValueError):
    pass


def normalize_room_name(raw):
    if raw is None:
        raise RoomNameError("Room name cannot be empty.")
    raw = raw.strip()
    if not raw:
        raise RoomNameError("Room name cannot be empty.")
    m = _ROOM_RE.fullmatch(raw.upper())
    if not m:
        raise RoomNameError(
            f"'{raw}' isn't a valid room name. Use a room number with an "
            f"optional single block letter, e.g. '503 B' or '301' — "
            f"nothing else is accepted."
        )
    prefix, number, suffix = m.groups()
    if prefix and suffix:
        raise RoomNameError(
            f"'{raw}' has letters on both sides of the number — use just "
            f"one, e.g. '503 B'."
        )
    letter = prefix or suffix
    return f"{number}-{letter}" if letter else number
