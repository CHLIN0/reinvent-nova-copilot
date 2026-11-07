# UX flow review: what each step should do, and why

Written 2026-11-06 after the first end-to-end use with a real attendee account. For each step: the job the attendee is trying to do, the design we consider best practice, what the app does today, and the gap. "Done" means implemented and run at least once; "gap" means not built yet.

## 0. Principles that apply to every step

| Principle | Reason |
|---|---|
| **One entry, one sign-in, one state.** Atlas (explore), Copilot (advise), routing (check) and RSVP (act) share one page, one Builder ID token and one plan. | Two apps with two logins is where attendees lose state and trust. |
| **Model proposes, code verifies, human commits.** Nova Pro never writes to the official schedule by itself; every write is a click, every write is read back. | Reservations are scarce and real. A wrong auto-RSVP costs a seat someone else wanted. |
| **Every specific is traceable.** Times, rooms, codes and feasibility come from tools, shown in the trace. Estimates are labelled. | The AI League lesson: confident and wrong is worse than vague. |
| **Default view = the attendee's own situation, not the whole catalog.** | 2,471 sessions is the catalog's problem, not the attendee's. |
| **Progressive disclosure.** Filters, traces, dropped-session reasons and the 3D map are one click away, not on the first screen. | First screen should answer "what is my day", not "what can I configure". |

## 1. Entry and sign-in

**Job:** get to a trusted, signed-in state in one step, and know it worked.

**Best practice:** Builder ID OAuth with PKCE on a loopback callback (the only form the official API allows). After the callback, return to the page that started the sign-in, never a fixed URL (validated against the loopback origins, so no open redirect). Show proof of sign-in that comes from the API, not from a flag: "signed in, N reserved, M favorites, read at HH:MM". Do not open two browser tabs for one login.

**Today:** done. Status bar reads `GetSchedule` and shows counts. Redirect uses the validated request origin.

**Gap:** the service restarts drop the in-memory token (by design); a short "you were signed out because the app restarted" message would avoid confusion. Two login buttons exist (Atlas banner and Copilot); they call the same flow, but one is enough.

## 2. First screen

**Job:** see my own conference at a glance.

**Best practice:** when signed in, open on the attendee's reserved sessions, on the first conference day (or today, during the event), with the time axis bounded to hours that have sessions. Reserved sessions visually distinct from suggestions. The catalog browser and filters are secondary.

**Today:** the time axis is now data-driven (earliest session hour to latest), replacing the 00:00 start that put six empty night hours on the first screen. Reserved and favorite sessions are synced into Atlas's plan after sign-in.

**Gap:** the default view is still the full catalog with filters open. Next: when `reserved` is non-empty, open in "my schedule" mode with filters collapsed, and show the Copilot briefing inline at the top rather than behind a button.

## 3. Discover

**Job:** find sessions worth my time, including ones I would not have searched for.

**Best practice:** two entrances, same result set: structured filters (topic, type, level, venue, day) for attendees who know what they want, and natural language through Copilot for attendees who know their goal but not the vocabulary. Results carry the reason they matched. Keep a share of adjacent topics so the list is not an echo of the query.

**Today:** both entrances exist. Copilot search ranks by matched terms and resolves session codes directly. Topic matching is word-level.

**Gap:** semantic similarity (embeddings over abstracts) for "related but not matching" sessions; the official API has no search, so this must be local. Showing *why* a session matched in the Atlas list.

## 4. Plan

**Job:** turn goals plus constraints into a day I can actually do.

**Best practice:** constraints come from a profile the attendee stated once (hotel, step limit, transport, mobility, diet, fixed commitments), not re-asked each time. Feasibility is computed (travel time vs gap minus buffer), not guessed. The plan shows what was dropped and why, and labels every travel number as an estimate. Fixed commitments become hard limits (`back_by`, `blocked`).

**Today:** done. Time-dependent Dijkstra for venue-to-venue travel, interval DP for session selection, hotel mapped to the nearest venue node (labelled approximate).

**Gap:** indoor routes are not modelled (the API has no floor plans), so a 2-minute room change and a 10-minute hall change look the same. Lunch and breaks are not planned unless the attendee states them.

## 5. Act (RSVP, favorites, Atlas plan)

**Job:** commit the plan without surprises.

**Best practice:** a write is always: propose (AI) → confirm (click, with the exact session named) → execute (official API, per-item result) → verify (read back) → show the outcome in the attendee's words ("session full", "conflicts with CMP321-R"). Favorites are cheap and reversible; reservations are scarce, so they get an extra confirm. Local plan (Atlas) is separate from official state and says so.

**Today:** done for favorites and reservations. Failure codes from the official API are shown with the conflicting session ids.

**Gap:** cancel reservation is not exposed (one more official call; add with the same confirm/read-back pattern). The local Atlas plan write runs after Atlas's own startup to avoid racing on the same browser database; the first version raced and showed Atlas's generic storage error.

## 6. Return visits and change detection

**Job:** when I come back, tell me what changed and what to do.

**Best practice:** keep a local snapshot of the last-seen official state. On open, diff it against the live state and brief in one short message: schedule changes, conflicts, gaps, one recommendation. Changes in the *catalog* (new or moved sessions) need a catalog snapshot too: keep session id → (start, end, room, abstract hash); new ids that match the attendee's interests become recommendations; moved sessions that are reserved become warnings.

**Today:** schedule snapshot and diff are done; the briefing runs when the Copilot panel opens.

**Gap:** catalog snapshot and diff are not built yet. This is the next feature: `local-private/profiles/<name>.catalog.json` with per-session hashes, refreshed on each visit, feeding `search_sessions(new_since=...)` so Nova Pro can say "three new sessions on agents since Tuesday; two fit your Wednesday gap".

## 7. Trust and transparency

**Job:** believe the answer enough to act on it.

**Best practice:** every answer shows which tools ran and what they returned (one click). Synthetic data is labelled on every screen it appears. The profile is shown to the attendee and editable, and its storage location is stated.

**Today:** done.

## Summary of next steps, in order

1. Signed-in default view: my schedule first, filters collapsed, briefing inline.
2. Catalog snapshot and "new since last visit" recommendations.
3. Cancel reservation with the same confirm/verify pattern.
4. Session-level "why it matched" in the Atlas list; embeddings for adjacent topics.
