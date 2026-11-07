# Routing and itinerary planning

Everything here is an **estimate**. The official AWS Events API returns sessions with
venue and room names, but no coordinates, floor plans, indoor graph or shuttle timetable.
The official re:Invent app has indoor wayfinding and live shuttle times. We do not reproduce
it and never claim to. Every `route()` result carries `estimate: True` and says so in `notes`.

## Recommendation

1. **Routing:** use time-dependent Dijkstra on a small hub graph: a door node and a shuttle stop
   for each venue, plus the four monorail stations. Walk, shuttle, monorail and rideshare are
   edge modes. A scheduled edge's cost depends on when you reach it: wait for the next
   departure, then ride.
2. **Itinerary:** use an exact DP over sessions sorted by start time, as in weighted interval
   scheduling. Two sessions can be consecutive only when the gap covers travel plus a buffer.
   Must-have sessions are locked. The DP maximises count or priority, then minimises travel.
3. **Why:** the data is small (about 12 nodes, about 60 sessions a day). With these algorithms we
   get exact answers in milliseconds using only the standard library, and every result can be
   explained. Heavier methods (A*, RAPTOR, orienteering solvers) speed up searches far larger than
   ours, or solve objectives we don't need.

## Options compared

| Approach | What it is | Fit here |
|---|---|---|
| Plain Dijkstra (static weights) | Shortest path with fixed edge costs | Exact, but it can't tell a shuttle leaving now from one leaving in 14 min. Enough only without `depart_at`, using the expected wait (half the headway). |
| A* + haversine heuristic | Dijkstra guided by a lower bound: straight-line distance divided by the fastest speed | Correct (the bound is admissible), but with about 12 nodes it saves nothing. A haversine bound on time is also weak when waits dominate. *Inference:* not worth the extra code. |
| **Time-dependent Dijkstra** | Edge cost = f(arrival time). Exact with one label per node when edges are FIFO (leaving later never arrives earlier) | **Chosen.** Headway waits are FIFO by construction (the `test_time_dependent_arrival_is_fifo` test checks this). |
| Time-expanded graph | One node per (stop, departure time) | Also exact, but the graph grows with the timetable. Without a real timetable it only adds size. |
| RAPTOR / Connection Scan | Round-based or sorted-connection public-transit routers, built for millions of trips | Built for city-scale timetables. Overkill for one shuttle network. |
| **DP over sorted sessions** | Weighted interval scheduling where "compatible" includes travel time and buffer | **Chosen.** Exact for "keep must-haves, maximise count or priority, then minimise travel". O(n²·K) with K = `max_sessions`. |
| Small exact search | Enumerate subsets | Exact but exponential. We use it only as a test oracle (`test_matches_brute_force_count`). |
| Orienteering Problem with Time Windows | Choose and order visits to maximise collected score within time windows | NP-hard. It matters when visit order is free. Sessions have fixed start and end times, so the order is fixed by time and the problem collapses to the interval DP. *Inference.* |

The algorithm facts above (Dijkstra 1959; A* by Hart, Nilsson and Raphael 1968; the FIFO
condition for time-dependent shortest paths; time-expanded vs time-dependent models, compared by Pyrga
et al. 2008; RAPTOR by Delling, Pajor and Werneck 2012; CSA by Dibbelt et al. 2013; weighted
interval scheduling in Kleinberg and Tardos; the OPTW survey by Vansteenwegen et al. 2011) come from
standard literature and were cited from memory. We did not re-fetch them tonight.

## Model (data/venue_graph.json, editable)

- **Venues:** `venetian, wynn, encore, caesars_forum, caesars_palace, mgm_grand, mandalay_bay`.
  Each lat/lon is the vertex mean of the OpenStreetMap building footprint in the earlier
  event-atlas project (© OpenStreetMap contributors, ODbL). Six venues carry event-atlas venue
  tags. Mandalay Bay uses OSM way 27858550. These are approximate centres, not entrances.
- **Monorail:** MGM Grand ↔ Horseshoe/Paris ↔ Flamingo/Caesars Palace ↔ Harrah's/The LINQ (the
  Caesars Forum station). Free with a badge at these four stations, per AWS Know Before You Go.
  Each station pair is one edge, so riding through costs one wait. Assumed 6 min headway,
  07:00–23:59 (the public range is every 4–12 min; hours run to 00:00–03:00 depending on the day).
- **Shuttle:** a stop at each venue, 4 min walk from the door. Assumed links: Venetian to every
  other venue, plus MGM↔Mandalay, Forum↔Mandalay and Forum↔MGM. 15 min headway, 06:30–22:00.
  Ride time = road distance (haversine × 1.5) at 18 km/h, plus 3 min boarding. **All assumed.**
  Official routes and times are in the app. A third-party guide says headways are shortest in
  the 30 minutes between session start times.
- **Walk:** Venetian–Wynn 10 min, Wynn–Encore 6, Venetian–Forum 15, Forum–Palace 15, MGM–Mandalay 30;
  plus walks between a venue and its monorail station. Steps = 100 per walking minute (*inference*:
  typical cadence). Same-venue room changes cost 6–10 min (Venetian 10, because Venetian/Palazzo/Expo
  is large).
- **Rideshare:** any venue pair. 8 min walk to and from the pickup zone, 10 min pickup wait,
  15 km/h on the road.
- **Search:** `prefer="fastest"` orders paths by (minutes, steps); `fewest_steps` by (steps, minutes).
  Without `depart_at`, scheduled legs cost half a headway and service hours are ignored. With it,
  waits are exact for the assumed schedule, and shuttles after 22:00 are skipped.

## Planner

- `check_itinerary(sessions, buffer_min=10)` sorts the sessions by start and gives each transition a status:
  `ok`, `tight` (slack < 5 min), `not_enough_time`, `overlap` or `new_day`, with gap, travel,
  slack (gap − travel − buffer), legs and steps.
- `plan_itinerary(candidates, must, day, prefer, buffer_min, max_sessions)`:
  1. Filter by `day` (ISO date or weekday name) and dedupe by id.
  2. If the must-haves conflict with each other, return `feasible: False` with `must_conflicts`
     and stop.
  3. DP: `dp[j][k]` = best chain of k sessions ending at j. A step i→j is allowed when
     travel + buffer fits the gap, and is blocked if it would skip a must-have between them.
     Score is lexicographic: (priority sum, −travel, −steps). Swap the last two for `fewest_steps`.
     `priority` is an optional field on a session (default 1).
  4. Every dropped session gets a reason: overlap with a chosen session, not enough time
     before or after a neighbour, the `max_sessions` cap, or another day.
- A session with an unknown venue is assumed to need 25 min of travel and is flagged.

## Prior work in the author's own repos (quick grep, 2026-11-06)

Searched the author's private project folders and knowledge wiki for
`dijkstra|haversine|a* search|openstreetmap|overpass` (local paths omitted from this public repo).

- **event-atlas** (earlier re:Invent map project): real OSM venue footprints. It documents that room,
  entrance, floor and indoor routing data are unavailable and that no route is invented.
  **Reused:** venue coordinates, and the stance against invented routes.
- **AI League pathfinding lambdas** (several versions): grid-maze BFS/heap pathfinding for a game.
  Not applicable to multimodal transit. Not reused.
- A vendored third-party benchmark (route planner over a game star map). Not reused.
- Knowledge wiki: nothing on routing.
- Nothing found on time-dependent routing or itinerary scheduling.

## Sources

- AWS, Know Before You Go (re:Invent): https://aws.amazon.com/events/reinvent/know-before-you-go/
- AWS Builder Center, Know Before You Go: Attending re:Invent 2025 in person:
  https://builder.aws.com/content/35iYepTKrrpDlEVwLGuPPfJ6X4y/know-before-you-go-attending-reinvent-2025-in-person
- Las Vegas Monorail stations: https://www.lvmonorail.com/stations/
- Las Vegas Advisor, monorail stops, times and prices: https://www.lasvegasadvisor.com/faq-transportation-monorail/
- NoCoverVegas re:Invent guide (third party; shuttle headway claim): https://nocovervegas.com/conventions/aws-reinvent/guide

Search results show AWS listing five 2025 venues (Wynn, Venetian, Caesars Forum, MGM Grand,
Mandalay Bay). Encore and Caesars Palace are kept because the contract includes them. Their
shuttle links are the least certain.

## Limitations

- Venue nodes are building centres, not session rooms or entrances. Indoor time is one constant per venue.
- The shuttle network, headways and service hours are assumptions, not the official schedule.
- No traffic, crowds, keynote surges or accessibility routing. Rideshare is not time-dependent.
- The monorail is cut off at 23:59, which is conservative (its hours run later most days).
- The planner treats travel as deterministic. `buffer_min` is the only hedge against variance.
