"""Synthetic AWS Events API pages for offline catalog tests and timing runs (no real catalog data).

FakeEventsAPI serves GetEvent and paginated ListSessions in the official response shape, counts
ListSessions calls, and can block or delay a page so tests control when a read finishes.
"""
import json
import random
import threading
import time

EVENT_ID = "reinvent2026"
VENUES = ("Venetian", "Caesars Forum", "MGM Grand", "Mandalay Bay", "Wynn", "Encore")
WORDS = ("serverless", "agents", "storage", "analytics", "security", "networking", "databases", "migration",
         "observability", "containers", "generative", "inference", "streaming", "governance", "resilience")


def raw_sessions(count=2516, seed=7):
    rnd = random.Random(seed)
    syllables = ("ka", "lo", "mi", "ra", "ten", "vo", "sel", "dri", "an", "cus", "po", "ze", "ther", "ul", "ix")
    vocabulary = list(WORDS) + ["".join(rnd.choice(syllables) for _ in range(rnd.randint(2, 4)))
                                for _ in range(3000)]
    items = []
    for n in range(count):
        day = 1 + n % 5
        words = [rnd.choice(WORDS) for _ in range(2)] + [rnd.choice(vocabulary) for _ in range(140)]
        items.append({
            "sessionId": f"syn-{n:05d}", "abbreviation": f"SYN{n:04d}",
            "title": f"Synthetic session {n} on {words[0]} and {words[1]}",
            "abstract": " ".join(words).capitalize() + ".",
            "sessionTime": {"date": f"2026-11-{29 + day:02d}" if day < 3 else f"2026-12-{day - 2:02d}",
                            "time": f"{8 + n % 10:02d}:{(n % 2) * 30:02d}", "length": "60",
                            "timezone": "America/Los_Angeles"},
            "venue": rnd.choice(VENUES), "room": f"Level {n % 5 + 1}, Room {n % 40}",
            "type": rnd.choice(("Breakout session", "Workshop", "Chalk talk", "Builders' session")),
            "level": rnd.choice(("100 - Foundational", "200 - Intermediate", "300 - Advanced", "400 - Expert")),
            "topics": rnd.sample(WORDS, 3), "tracks": [rnd.choice(WORDS)], "services": rnd.sample(WORDS, 2),
            "areasOfInterest": rnd.sample(WORDS, 2), "roles": ["Developer / Engineer"],
            "speakers": [{"name": f"Speaker {n}-{k}"} for k in range(1 + n % 3)],
            "isReservable": True, "seatAvailability": rnd.choice(("available", "limited", "unavailable")),
        })
    return items


class FakeEventsAPI:
    """Transport for both adapters; page_delay sleeps per ListSessions page (real seconds)."""

    def __init__(self, items=None, page_size=250, page_delay=0.0):
        self.items = raw_sessions() if items is None else items
        self.page_size = page_size
        self.page_delay = page_delay
        self.list_calls = 0
        self.gate = None  # a threading.Event: ListSessions pages wait for it when set
        self.entered = threading.Event()
        self._lock = threading.Lock()

    def block(self):
        """Hold ListSessions pages until the returned event is set; entered tells when one arrived."""
        self.entered.clear()
        self.gate = threading.Event()
        return self.gate

    def page(self, next_token):
        start = int(next_token or 0)
        with self._lock:
            self.list_calls += 1
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.page_delay:
            time.sleep(self.page_delay)
        body = {"items": self.items[start:start + self.page_size], "totalCount": len(self.items)}
        if start + self.page_size < len(self.items):
            body["nextToken"] = str(start + self.page_size)
        return body

    def event(self):
        return {"event": {"eventId": EVENT_ID, "timezone": "America/Los_Angeles",
                          "supportedLanguageCodes": ["en-US"]}}

    def atlas(self, path, query, token, timeout):
        """explorer.official_catalog transport(path, query, token, timeout)."""
        if path.endswith("/sessions"):
            return 200, {"Content-Language": "en-US"}, json.dumps(self.page(query.get("nextToken"))).encode()
        return 200, {}, json.dumps(self.event()).encode()

    def copilot(self, method, path, query, body, token):
        """atlas.catalog._transport(method, path, query, body, token)."""
        if path.endswith("/sessions"):
            return 200, {}, json.dumps(self.page((query or {}).get("nextToken"))).encode()
        return 200, {}, json.dumps(self.event()).encode()
