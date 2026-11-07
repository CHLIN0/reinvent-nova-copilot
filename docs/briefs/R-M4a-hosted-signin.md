# M4a · Hosted deployment and the sign-in constraint (Codex, read-only, memo)

Write `docs/research/hosted-signin-2026-11.md`. Dated sources; mark unverified items. Finish within about 40 minutes.

Context: the AWS Events API uses Builder ID OAuth (authorization code + PKCE); as read on 2026-10-26, the only allowed redirect URIs are http://127.0.0.1:{8484-8489}/callback (see `atlas/official_auth.py` and `explorer/official_auth.py`). BR wants a cloud deployment so other attendees can use the app themselves, plus open source (MIT).

Re-read the current official docs (https://docs.aws.amazon.com/events/latest/devguide/, especially "Signing an attendee in", endpoints and values, token handling) and answer: can a hosted web app complete sign-in today? Evaluate: hosted redirect (allowed or not), device-style flow, a small local helper the user runs that completes OAuth and forwards a token to the hosted app (security implications), a desktop/Electron wrapper, or asking AWS for a registered redirect. For each: feasibility today, security, user friction, and effort. Then sketch the minimal hosted architecture on AWS for the viable path (container, per-user server-side state, secrets, cost ledger per user) with a monthly cost estimate for 100 users. End with one recommendation or "not possible today" and what to ask AWS.
