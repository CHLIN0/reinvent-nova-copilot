# re:Invent Nova Copilot

An Amazon Nova Pro agent that **acts** on the official re:Invent 2026 Event Catalog API instead of only chatting about re:Invent.
Ask it a question in plain language. It looks up real sessions, checks whether you can actually get from one venue to the next in time, builds a feasible day, and (only after you confirm) saves your picks as favorites in your official re:Invent schedule.

When you are signed in, the agent also connects to the **official AWS Events MCP server** and gives Nova Pro its read-only tools alongside its own.

Every capability is also exposed as an **MCP server**, so you can plug the same tools into any MCP client next to the official `https://api.awsevents.com/mcp` server.

Built for the AWS re:Invent Event Catalog API Hackathon (2026).

## Why

re:Invent is spread over several Las Vegas venues, with thousands of sessions. A generic chatbot can give good advice, but it cannot know which sessions exist, when they run, or whether a 15-minute gap between The Venetian and MGM Grand is enough. That leads to confident and wrong plans.

This project started from a Nova Pro prompt that was tuned to give re:Invent veteran advice (direct answer first, cover every condition, never invent times/rooms/codes). We then gave the model tools:

| Need | Tool | Backed by |
|---|---|---|
| "Which sessions match what I want?" | `search_sessions`, `get_session` | Official Events API `ListSessions` / `GetSession` (local filtering, since the API has no server-side search) |
| "What have I already booked?" | `get_my_schedule` | Official `GetSchedule` |
| "Can I make it from A to B?" | `route_between` | Time-dependent multimodal routing (walk / badge shuttle / monorail / rideshare) |
| "Is my day realistic?" | `check_itinerary` | Gap vs. travel time + buffer, per transition |
| "Build me a day" | `plan_itinerary` | Exact DP over sessions sorted by start time, with must-attend sessions locked |
| "Remember where I stay, how I move, what is fixed" | `get_profile`, `update_profile` | Local per-attendee profile (hotel, transport, step limit, mobility, diet, fixed commitments, special arrangements, interests). Plans start and end at the hotel; fixed commitments become `back_by` / `blocked` limits |
| "Save these" | `add_favorites` (write, needs confirmation) | Official `AssociateFavorites`, then read back via `GetSchedule` |

Prompt approach: it keeps the Nova Pro prompt structure and re:Invent veteran attitude from the author's prompt-only advisor, but flips the old rule "never state specifics" into **"look specifics up with tools and cite them; never state one that no tool returned."**

## Event Atlas

`explorer/` is the author's Event Atlas agenda explorer (calendars + 3D campus), built earlier in the hackathon period on the same official API and now served by `web.py` in the same process and origin. Third-party components are listed in `explorer/THIRD_PARTY_NOTICES.md` (map data (c) OpenStreetMap contributors, ODbL). Rebuild its UI with `cd explorer/ui && npm ci && npm run build`.

## Design notes

`docs/ux-flow.md` reviews each step of the attendee flow (sign-in, first screen, discover, plan, act, return visits, trust): the design we consider best practice, what is built, and what is next. `docs/routing.md` covers the routing and itinerary algorithms.

## Architecture

```
 user ──► chat.py ──► atlas/agent.py ──(Bedrock Converse, tool use)──► Amazon Nova Pro
                          │
                          ▼
                    atlas/tools.py  ◄──── atlas/mcp_server.py ◄── any MCP client
                     │      │      │
        atlas/catalog.py  atlas/routing.py  atlas/planner.py
              │
   atlas/official_auth.py (Builder ID OAuth PKCE, loopback, token in memory)
              │
   https://api.awsevents.com/v1  +  https://api.awsevents.com/mcp (official_mcp.py)
```

- Deterministic code does what must be correct (IDs, times, conflicts, travel feasibility, write results).
- Nova Pro does what language models are good at (understanding intent, choosing tools, explaining trade-offs).
- Tokens never reach the model, logs, or disk.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt` (`boto3`, `mcp`)
- AWS credentials with Amazon Bedrock access to Amazon Nova Pro (`us.amazon.nova-pro-v1:0`, default region `us-east-1`)
- For live catalog data: an AWS Builder ID that is registered for re:Invent 2026. Without it, the app uses a clearly labelled **synthetic** demo catalog.

## Run the web app (recommended)

```sh
pip install -r requirements.txt
cp .env.example .env   # add Bedrock credentials, or use AWS_PROFILE
python3 web.py --profile yourname
```

Open http://127.0.0.1:8500/ . One page, one sign-in:

- **Event Atlas** (main view): the official catalog with multi-select filters, five-day and single-day calendars, and a 3D campus map built from OpenStreetMap footprints.
- **Nova Copilot** (button at bottom right): Amazon Nova Pro answers with tool-checked facts, plans your day from and back to your hotel with route estimates, and adds the plan to your Event Atlas calendar in one click.
- **Sign in with AWS Builder ID** once; both views share the same in-memory token. Without sign-in, the copilot uses the synthetic demo catalog.
- `/copilot` is a chat-only view.

## Run (command line)

```sh
pip install -r requirements.txt

# Offline demo against the synthetic catalog (still needs Bedrock for Nova Pro)
python3 chat.py --trace "I'm a mid-level developer into AI agents and security. On Tuesday I must attend the MCP with OAuth hands-on session. Plan the rest of my Tuesday with as little walking as possible, and tell me which transitions are tight."

# Interactive, with a personal profile (stored locally in local-private/profiles/)
python3 chat.py --profile alex

# Live official catalog: sign in with your Builder ID in the browser when prompted
python3 chat.py --live
```

Credentials: copy `.env.example` to `.env` (git-ignored) or use any standard AWS credential source. A real run of the command above, with the tool trace, is in `docs/demo-transcript.txt`.

Configuration via environment variables: `AWS_PROFILE`, `AWS_REGION` (default `us-east-1`), `NOVA_MODEL_ID` (default `us.amazon.nova-pro-v1:0`).

## Use as an MCP server

```sh
python3 -m atlas.mcp_server
```

The MCP server serves the synthetic catalog (route and plan tools work fully). For your live catalog, use `chat.py --live`, or register the official server next to it.

Example client config, alongside the official server:

```json
{
  "mcpServers": {
    "reinvent-nova-copilot": { "command": "python3", "args": ["-m", "atlas.mcp_server"], "cwd": "/path/to/reinvent-nova-copilot" },
    "aws-events": { "type": "http", "url": "https://api.awsevents.com/mcp" }
  }
}
```

## Tests

```sh
python3 -m unittest discover -s tests
```

Tests are offline: mocked HTTP for the official API (pagination, 401, 429), a mocked Bedrock client for the agent loop, and fixture-based routing/planning.

## Data and safety boundaries

- `data/fixture_sessions.json` is **synthetic**, written for this project. It is not the real catalog. The real catalog is access-controlled, so it is fetched live per user and never committed.
- OAuth uses the official loopback flow (ports 8484–8488, `/callback`, PKCE). Access tokens live in process memory only.
- Attendee profiles are stored only on the local machine (`local-private/profiles/<name>.json`, git-ignored, mode 0600) and are never sent to AWS Events. They reach Nova Pro on Amazon Bedrock only as `get_profile` tool results in that conversation.
- Write actions to AWS Events are limited to favorites, require explicit confirmation, report per-item results, and are verified by reading the schedule back. The agent never reserves or cancels seats.
- Travel times are **estimates** from a venue graph (walk speed, shuttle headway, monorail, rideshare). They are not official wayfinding. Indoor routes are not modelled, because the API provides no floor plans.

## Limitations

- Routing is venue-to-venue. Indoor paths, live crowding and live shuttle positions are not available through the API.
- Live mode needs a registered attendee. Judges without one can run the synthetic demo.
- Nova Pro can still phrase things imperfectly. Facts that matter (times, rooms, feasibility) come from tools, and the trace (`--trace`) shows which tool supplied each one.

## Originality

All code in this repository was written during the hackathon period. The official API client is adapted from the author's own earlier local prototype (also built during the hackathon period). The system prompt builds on the author's own Nova Pro prompt-engineering work. No third-party code is vendored beyond the packages in `requirements.txt`.

## License

MIT (see `LICENSE`).
