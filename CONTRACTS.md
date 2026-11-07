# Module contracts and ownership (hackathon build, 2026-11-06)

Deadline: submission 2026-11-06 23:59 PST. Module owners must be done by 23:00 PST.
Python 3.12, deps limited to `boto3` and `mcp` (both installed). Shapes in `atlas/models.py`.
Each owner edits ONLY their files. Do not commit; the lead integrates and commits.

## Owner A: official data layer (`atlas/official_auth.py`, `atlas/catalog.py`, `atlas/official_mcp.py`, `data/fixture_sessions.json`, `tests/test_catalog.py`)
- `load_sessions(source: str = "auto") -> list[Session]`  "fixture" | "live" | "auto" (live if signed in, else fixture)
- `search_sessions(query: str = "", types: list[str] | None = None, levels: list[str] | None = None, topics: list[str] | None = None, day: str | None = None, venue: str | None = None, limit: int = 20) -> list[Session]`
- `get_session(session_id: str) -> Session | None`
- `get_schedule() -> dict`  live only: reservations, favorites, personal time (official GetSchedule)
- `add_favorites(session_ids: list[str]) -> dict`  live only, per-item result, then read back GetSchedule
- `sign_in()`  OAuth PKCE loopback (ports 8484-8488, /callback), token in memory only
- `official_mcp.call_tool(name, arguments) -> dict`  proxy to https://api.awsevents.com/mcp with the same token
- Fixture: ~60 SYNTHETIC sessions, clearly labelled synthetic, realistic spread over Mon-Thu across venues.

## Owner B: routing + itinerary (`atlas/routing.py`, `atlas/planner.py`, `docs/routing.md`, `tests/test_routing.py`, `tests/test_planner.py`)
- `VENUES: dict[str, dict]` canonical keys: venetian, wynn, encore, caesars_forum, caesars_palace, mgm_grand, mandalay_bay (+ name, lat, lon)
- `route(from_venue: str, to_venue: str, depart_at: str | None = None, prefer: str = "fastest") -> Route`  prefer: fastest | fewest_steps
- `check_itinerary(sessions: list[Session], buffer_min: int = 10) -> dict` transitions with slack, conflicts, total steps
- `plan_itinerary(candidates: list[Session], must: list[str] = [], day: str | None = None, prefer: str = "fastest", buffer_min: int = 10, max_sessions: int = 6) -> dict` best feasible set + explanation of what was dropped and why

## Owner C: Nova Pro agent + MCP server (`atlas/tools.py`, `atlas/agent.py`, `atlas/mcp_server.py`, `atlas/prompts.py`, `chat.py`, `tests/test_agent.py`)
- `tools.py`: tool specs (JSON schema) + dispatcher wrapping A and B functions
- `mcp_server.py`: stdio MCP server exposing the same tools (any MCP client can use them)
- `agent.py`: Bedrock Converse tool-use loop with Amazon Nova Pro (`us.amazon.nova-pro-v1:0`), max N tool rounds
- `chat.py`: CLI `python chat.py "question"` and interactive mode
- Write actions (favorites) require explicit user confirmation in the loop.
