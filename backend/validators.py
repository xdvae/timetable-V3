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


_DIGITS_RE = re.compile(r"^\d{1,4}$")


def compose_room_name(block, number):
    """Canonical room name from a Block letter (A-Z or blank) + room number.

    The number must be digits only (1-4 digits). The result uses the same
    canonical form as normalize_room_name(): "101" or "101-A".
    """
    block = (block or "").strip().upper()
    number = "" if number is None else str(number).strip()
    if not number:
        err = RoomNameError("Enter a room number.")
        err.field = "number"
        raise err
    if not _DIGITS_RE.fullmatch(number):
        err = RoomNameError("Room number must be digits only (e.g. 101).")
        err.field = "number"
        raise err
    if block and (len(block) != 1 or not ("A" <= block <= "Z")):
        err = RoomNameError("Block must be a single letter from A to Z.")
        err.field = "block"
        raise err
    return f"{number}-{block}" if block else number


def split_room_name(name):
    """(block, number) for a canonical room name; block is None if absent."""
    m = re.fullmatch(r"(\d{1,4})(?:-([A-Z]))?", name or "")
    if not m:
        return None, name
    return m.group(2), m.group(1)
