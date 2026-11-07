# From re:Invent chatbot to re:Invent agent: giving Amazon Nova Pro the official Event Catalog API

<!-- Builder Center article draft. Items marked [TBD] are filled in after integration. -->

## The problem: good advice, wrong plans

A few weeks ago I competed in an AWS AI League prompt-engineering final. The task was to make Amazon Nova Pro the best possible re:Invent advisor, with nothing but a prompt. The prompt that won followed a few strict rules: give the direct answer first, address every condition the attendee states, and never invent dates, times, rooms or session codes.

That last rule is the catch. A prompt-only chatbot gives good advice *because* it refuses to be specific. Ask it "Can I go from a 10:00 session at The Venetian to an 11:00 session at MGM Grand?" and the best it can honestly say is "check the app".

The new re:Invent Event Catalog API and MCP server remove that limit. So I asked: what if the same tuned Nova Pro could *look things up and check them* before answering?

## What I built

**re:Invent Nova Copilot**: an Amazon Nova Pro agent (Amazon Bedrock Converse API with tool use) and an MCP server, built on the official Events API.

You ask in plain language, for example: *"I'm into agents and security, I have to be at MGM Grand at 14:00 on Tuesday, plan the rest of my day with as little walking as possible."* The agent then works in five steps:

1. **Finds real sessions**: `search_sessions` / `get_session` over the official catalog (`ListSessions`, `GetSession`).
2. **Reads what you already have**: `get_my_schedule` (`GetSchedule`).
3. **Checks travel**: `route_between` computes walk, badge-shuttle, monorail and rideshare options between venues.
4. **Builds a feasible day**: `plan_itinerary` locks your must-attend sessions and picks the best set that you can physically reach, explaining what it dropped and why.
5. **Saves your picks only after you confirm**: `add_favorites` (`AssociateFavorites`) reports per-item results, then reads your schedule back to verify.

The same tools are exposed through an MCP server, so they can sit next to the official `https://api.awsevents.com/mcp` in any MCP client.

A real run (Nova Pro on Amazon Bedrock, synthetic demo catalog), with the tool trace:

```text
$ python3 chat.py --trace "I'm a mid-level developer into AI agents and security. On Tuesday I must attend the MCP with OAuth hands-on session. Plan the rest of my Tuesday with as little walking as possible, and tell me which transitions are tight."

--- trace: 4 tool call(s), 4 round(s), stop=end_turn
1. search_sessions({"query": "MCP with OAuth hands-on", "limit": 1, "day": "Tue"}) -> ok: {"count": 1, "sessions": [{"id": "syn-0010", "code": "SYN-AI410", "title": "R...
2. search_sessions({"venue": "mgm_grand", "topics": ["AI agents", "security"], "limit": 10, "day": "Tue"}) -> ok: {"count": 1, "sessions": [{"id": "syn-0010", "code": ...
3. search_sessions({"topics": ["AI agents", "security"], "limit": 10, "day": "Tue"}) -> ok: {"count": 7, "sessions": [{"id": "syn-k001", "code": "SYN-KEY01", "title": ...
4. plan_itinerary({"prefer": "fewest_steps", "must": ["syn-0010"], "candidate_ids": ["syn-k001", "syn-0002", "syn-0026", "syn-0006", "syn-0030", "syn-0022"], "day": "T...
Here's your planned Tuesday with minimal walking:

- 09:00 - 10:00 SYN-SEC406, Incident response game day, caesars_forum
- 12:00 - 13:00 SYN-AI410, Remote MCP servers with OAuth: a hands-on build, mgm_grand (must-attend)
- 16:30 - 17:30 SYN-SEC302, Detecting credential misuse in minutes, venetian

Transitions:
- From SYN-SEC406 to SYN-AI410: 27.6 minutes by rideshare with 82.4 minutes of slack.
- From SYN-AI410 to SYN-SEC302: 29.7 minutes by rideshare with 170.3 minutes of slack.

No tight transitions were found. The sessions SYN-KEY01, SYN-AI202, SYN-AI306, and SYN-SEC110 were dropped due to time overlaps or insufficient time after the previous...

Next, confirm this plan in the AWS Events app and adjust as needed.
```

## How it uses the API and MCP

| Official capability | How the project uses it |
|---|---|
| Builder ID OAuth (authorization code + PKCE, loopback callback) | Local sign-in on ports 8484–8488. The token stays in memory and never reaches the model or logs. |
| `ListSessions` with pagination | Full catalog loaded until `nextToken` is absent. Search and filtering run locally, because the API has no server-side search. |
| `GetSession` | Full details when the agent cites a session. |
| `GetSchedule` | Grounds the plan in what the attendee already has. Used again after every write to verify. |
| `AssociateFavorites` | The only write the agent may perform, gated by explicit user confirmation. |
| Remote MCP server | The project's own MCP server is registered next to the official `https://api.awsevents.com/mcp` in the same client. `official_mcp.py` is a small client for the official server, reusing the same sign-in token. |
| Quotas and errors | 429 honours `Retry-After`. 401/403 stop and ask to sign in again or check registration. Writes are reconciled by reading back, since there is no idempotency key. |

## Design decisions

**Deterministic code for facts, the model for judgment.** Session IDs, times, conflicts, travel feasibility and write results are computed by code. Nova Pro decides which tools to call and explains the trade-offs. The prompt keeps the AI League rules, with one change: it *may* state a time, room or code, **but only if a tool returned it**, and it cites the session code.

**Routing: time-dependent Dijkstra on a small hub graph.** Venue-to-venue travel at re:Invent is multimodal and time-dependent: a shuttle trip depends on when the next shuttle leaves. Each venue has a door node and a shuttle-stop node, and the monorail stations are nodes too. Edges are walk, badge shuttle (headway-based wait), monorail and rideshare. An edge's cost is a function of the time you reach it. Waiting for the next departure is FIFO (leaving later never gets you there earlier), so plain Dijkstra with time-dependent costs stays exact. I compared the alternatives:

| Approach | Verdict here |
|---|---|
| Static Dijkstra | Exact, but cannot tell "shuttle now" from "shuttle in 14 minutes" |
| A* with a haversine heuristic | Correct, but on about 12 nodes it saves nothing, and waits make the bound weak |
| Time-expanded graph, RAPTOR, Connection Scan | Built for city-scale timetables. Overkill for one shuttle network |
| **Time-dependent Dijkstra** | **Chosen**: exact, milliseconds, explainable |

**Itinerary: exact DP instead of a heuristic.** Picking sessions sounds like an orienteering problem, which is NP-hard. But sessions have fixed start and end times, so the order is already fixed by time, and the problem collapses into weighted interval scheduling. Two sessions are compatible only if the gap covers the travel time plus a buffer. Must-attend sessions are locked. The DP maximises the number or priority of sessions, then minimises travel. Every dropped session comes back with a reason ("time overlap with chosen X", "cannot reach in time: needs 21 min, gap 15").

All travel times are labelled estimates. The API has no floor plans, so indoor routes are not modelled and not faked.

**Safe by default.** The agent never reserves or cancels seats. Favorites need a yes, and the result is verified against `GetSchedule`.

## Try it

Repository: [TBD: GitHub URL]

```sh
pip install -r requirements.txt
python3 chat.py --trace "Plan my Tuesday around agents and security with minimal walking"
```

Without a registered Builder ID it runs on a clearly labelled synthetic catalog. With one, run `python3 chat.py --live` to use your real catalog and schedule.

## What I learned

- Prompt engineering got Nova Pro to *behave* like a veteran. Tools got it to be *right*. The "never invent specifics" rule turns into "only state specifics from tools", and that changes how useful the answers can be.
- At this scale (a handful of venues, a few thousand sessions), exact algorithms are cheap. There is no need to approximate.
- The hardest parts were not the model. They were time zones, pagination, partial write results and being honest about what the data does not contain.

## Limits and next steps

- Indoor wayfinding, live crowding and live shuttle positions are not available through the API.
- Next: a map view (I have an earlier 3D campus prototype), multilingual explanations for non-English attendees, and group planning with explicit consent.
