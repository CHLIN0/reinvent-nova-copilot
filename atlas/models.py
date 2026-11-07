"""Shared data shapes. Every module exchanges plain dicts in these shapes."""
from typing import TypedDict


class Session(TypedDict, total=False):
    id: str            # official session ID (never invented)
    code: str          # e.g. "AIM301"
    title: str
    abstract: str
    type: str          # Breakout, Workshop, Chalk talk, Builders' session, Code talk, Keynote
    level: str         # "100".."400"
    topics: list[str]
    start: str         # ISO 8601 with offset, Las Vegas time (-08:00)
    end: str
    venue: str         # canonical venue key, see atlas.routing.VENUES
    room: str
    seats: str         # coarse availability if provided


class Leg(TypedDict):
    mode: str          # walk | shuttle | monorail | rideshare
    from_node: str
    to_node: str
    minutes: float
    steps: int


class Route(TypedDict):
    from_venue: str
    to_venue: str
    minutes: float     # door-to-door estimate incl. waits
    steps: int
    legs: list[Leg]
    estimate: bool     # True = model estimate, not official wayfinding
