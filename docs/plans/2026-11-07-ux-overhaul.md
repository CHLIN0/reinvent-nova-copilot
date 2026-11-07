# Plan: make re:Invent Nova Copilot something an attendee wants to use

Status: **draft for BR's review, 2026-11-07**. Nothing below is started. Hackathon submission is done (2026-11-06 23:50 PST); this is the post-submission overhaul.

## 1. Goal (BR's words, condensed)

One system where the official API, route planning and AI advice are one flow: intuitive, highly available, and worth coming back to. Remove or transform what does not earn its place. No decoration, no speculative features.

Success looks like: an attendee signs in once, sees *their* re:Invent (not a 2,471-session catalog), asks for help in plain language, gets a plan that respects every reservation and limit they have, commits it with one click per session, and on the next visit is told what changed and what to do about it. All of that works in a browser with site storage blocked, after a server restart, and after the token expires.

## 2. What the walkthrough found (2026-11-07 00:00 PST, BR's Chrome, signed in, real catalog)

| # | Observation | Evidence | Why it matters |
|---|---|---|---|
| P1 | **Browser storage is denied** in BR's Chrome for this origin: IndexedDB `UnknownError: The user denied permission`, `localStorage` `SecurityError`. Atlas shows "無法安全儲存本機安排" and "我的安排 0" right next to a banner saying "9 reserved". | JS probe in the page | Every plan feature that lives in the browser is dead for this user. Availability requirement fails on day one. |
| P2 | **First screen is the whole catalog**: 2,471 sessions, first cards are "Wishing Booths", "Breakfast", "Hydrate & Help". Reserved sessions are not distinguished. The attendee's own day is invisible. | Screenshot 00:00 | The product answers "what exists" instead of "what is my day". |
| P3 | **Planner ignored real reservations.** Asked to plan Wednesday "around my reserved sessions, keep my reservations", Nova Pro called `plan_itinerary` without `must`; the plan overlaps GHJ315 (08:00–10:00) and DVT415-R2 (10:30–11:30). | Tool trace in the panel | A plan that double-books the attendee is worse than no plan. Correctness cannot depend on the model remembering a parameter. |
| P4 | **Briefing claimed "feasible, no conflicts"** after only `get_profile` + `get_my_schedule`; it never called `check_itinerary`. | Tool trace | Unverified claim presented as checked. Violates the project's own rule. |
| P5 | **Answer noise**: 20+ dropped codes dumped inline, arbitrary `max_sessions: 4`, long prose in a narrow panel, occasional Markdown asterisks. | Screenshot 00:01 | Hard to scan; the useful part (4 sessions, 2 transitions) is buried. |
| P6 | **Three "plans"** (Atlas 我的安排, Copilot "Your day", official schedule), two sign-in buttons, sync by page reload, Copilot hidden behind a corner button. | UI | The attendee has to understand our architecture to use the app. |
| P7 | **Restart = silent sign-out**; token lasts 60 min with no warning. | Server behaviour | Confusing failure with no explanation. |
| P8 | Duplicates: `/copilot` chat-only page, CLI, two login paths, briefing text repeated in chat. | Code | Surface area without users. |
| What works | Sign-in; official schedule read-back (9 reserved, 5 favorites, codes/titles/rooms resolved); real-catalog search and routing; RSVP/favorite cards; data-driven calendar hours; tool trace. | Walkthrough | Keep. |

## 3. Non-goals (explicitly out)

Indoor routing; multi-user or team features; cloud deployment; other LLMs; changes to the 3D map; new visual styling beyond what a task needs; anything not traceable to a row in section 2 or a goal in section 1.

## 4. Tasks (one session each, Opus 5.5, own branch, PR to `main`)

Each task has an owner session, acceptance criteria that a reviewer can check, and a "must not" list to prevent drift. Order matters: T1 and T2 are foundations.

### T1 · State lives on the server (fixes P1, P6)
- Replace Atlas's browser plan store with a server plan: `GET/POST /api/plan` backed by `local-private/profiles/<name>.state.json`. The plan = official reservations + official favorites (read from `GetSchedule`) + local picks, with a `source` per item.
- Atlas reads the plan from the server and renders it; "我的安排" shows reserved/favorite/local with distinct marks. Filters live in the URL hash only; no localStorage.
- Copilot's "add to plan" writes to the same endpoint; no page reload.
- **Acceptance**: with site data blocked in Chrome, "我的安排" shows 9 reserved and 5 favorites; no storage error is ever rendered; adding a session from Copilot appears in the calendar without reload.
- **Must not**: add a database; change the 3D map; touch `explorer/ui` beyond the plan store and its consumers.

### T2 · Reservations are locked in code (fixes P3, P4)
- `plan_itinerary` and `check_itinerary` automatically load the official schedule when signed in: reserved sessions are `must`, their times are blocked, favorites are candidates with priority. The model cannot omit them.
- The briefing calls `check_itinerary` per conference day before saying anything about feasibility; if the tool was not called, the server strips feasibility claims from the text.
- **Acceptance**: the Wednesday case from the walkthrough yields no suggested session overlapping GHJ315, DVT415-R2 or SEC407-R1; offline test with a fixture schedule; scenario battery asserts `check_itinerary` appears in every briefing trace.
- **Must not**: change the routing algorithm; add new tools beyond what exists.

### T3 · Signed-in first screen = "My re:Invent" (fixes P2, P6)
- After sign-in: open on the first conference day (or today during the event) in day view, reserved sessions highlighted, gaps between them marked, Copilot's briefing shown at the top of the page, not behind a corner button.
- Catalog browsing becomes a second tab ("Explore"); filters collapsed by default.
- One sign-in control; the Copilot panel is a persistent side panel with a toggle, not a floating button.
- **Acceptance**: screenshot in BR's Chrome: first paint shows BR's Monday with CMP321-R, INV538, GHJ308-S-R and the gaps; no breakfast/booth cards unless Explore is opened.
- **Must not**: redesign colours/typography; remove the five-day view; add animations.
- Depends on T1.

### T4 · Answers that fit a panel (fixes P5)
- Prompt + server post-processing: plan answers = lines for leave hotel / sessions / back; transitions as one line each; dropped list collapsed to "N dropped (3 shown)"; no Markdown symbols; yes/no questions answered in the first sentence; `max_sessions` derived from the day's free windows, not guessed.
- **Acceptance**: scenario battery of 8 real-catalog questions; each answer ≤ 160 words, first sentence rule checked by test, no `**`.
- **Must not**: change tool contracts; add new tools.

### T5 · Sessions that survive time (fixes P7)
- Token expiry shown ("signed in, 42 min left"), re-sign-in prompt before expiry, refresh token used where the API allows; on server restart the page says why it is signed out.
- **Acceptance**: manual test: wait past expiry → one click restores; restart → clear message.
- **Must not**: persist tokens to disk.

### T6 · New and changed sessions since last visit (BR's requirement, not yet built)
- Server keeps a catalog snapshot per profile: session id → (start, end, room, abstract hash). On each visit: new ids, moved reserved sessions, cancelled reserved sessions. Briefing reports them; new sessions matching profile interests are recommended with codes.
- **Acceptance**: fixture test with a modified catalog; briefing names the new session and the moved reservation.
- Depends on T1.

### T7 · RSVP lifecycle
- Cancel reservation with the same confirm → official call → read-back; seat status shown on cards; result codes in plain words.
- **Acceptance**: offline test; one real cancel+re-reserve on a low-stakes session, with BR's go-ahead.

### T8 · Remove duplicates (fixes P8)
- Delete `/copilot` chat-only page and its `web/index.html`; keep CLI (`chat.py`) for judges and tests; one sign-in path; one place where the plan is shown.
- **Acceptance**: `git grep` shows no dead routes; README updated.

### T9 · Reliability gate
- Scenario battery (offline, mocked Bedrock) runs in CI; error states (401/403/429, Bedrock unavailable) render user-facing text; `python3 -m unittest` green.

## 5. How the work runs

1. **Host (this session)** writes one brief per task from this file, starts one Opus 5.5 session per task in its own worktree, three in parallel at most, in the order T1+T2 → T3+T4+T5 → T6+T7+T8 → T9.
2. Each session ends with a PR to `main`, its tests, and (for UI tasks) a screenshot from a real run.
3. **Review gate, every PR**: Codex review with `gpt-6.1-sol` against a fixed checklist: scope equals the task's acceptance and nothing else; no speculative abstraction; no new dependency; tests present and meaningful; no secrets or local paths; UI claims backed by a screenshot. Findings go back to the session; the host re-checks the fix.
4. **Host verification before merge**: the host runs the branch and checks the acceptance criteria in BR's Chrome (signed in), then merges sequentially and rebases the next branch.
5. **BR's gates**: approve this plan (sections 1–4); approve any real write to the official schedule (T7); approve removals (T8).
6. Usage check before each fan-out (rule in execution-routing). Codex availability is verified before the first PR (the 2026-11-06 review did not return within 20 minutes).

## 6. Open questions for BR

1. T3: default to the first conference day, or to "today" once the event starts? (Proposal: first day until 2026-11-30, then today.)
2. T8: delete `/copilot` and the CLI, or keep the CLI for judges and tests? (Proposal: keep CLI, delete `/copilot`.)
3. T7: cancel-reservation is a real write; is one supervised test on a low-stakes session acceptable?
4. Anything in section 2 you disagree with, or a pain point I did not see?
