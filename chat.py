"""re:Invent Nova Copilot CLI.

    python3 chat.py "Plan my Tuesday around GenAI workshops at the Venetian"
    python3 chat.py              # interactive; 'reset' clears history, 'exit' quits
    python3 chat.py --trace "..."  # also print the tools Nova called
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from atlas.agent import Agent, AgentResult


def confirm_cli(name: str, args: dict) -> bool:
    ids = ", ".join(args.get("session_ids") or [])
    try:
        reply = input(f"\nNova wants to run {name} for: {ids}\nThis changes your AWS Events schedule. Proceed? [y/N] ")
    except EOFError:
        return False
    return reply.strip().lower() in ("y", "yes")


def print_trace(res: AgentResult) -> None:
    print(f"\n--- trace: {len(res.trace)} tool call(s), {res.rounds} round(s), stop={res.stop_reason}", file=sys.stderr)
    for i, c in enumerate(res.trace, 1):
        flag = "ok" if c.ok else "ERROR"
        extra = "" if c.confirmed is None else f" confirmed={c.confirmed}"
        out = json.dumps(c.result, ensure_ascii=False)
        print(f"{i}. {c.name}({json.dumps(c.input, ensure_ascii=False)}) -> {flag}{extra}: {out[:300]}{'...' if len(out) > 300 else ''}", file=sys.stderr)


def run_one(agent: Agent, q: str, trace: bool) -> None:
    from atlas.format import format_answer

    res = agent.ask(q)
    print(format_answer(res.text, res.trace, q))
    if trace:
        print_trace(res)


def main() -> int:
    p = argparse.ArgumentParser(
        description="re:Invent Nova Copilot (Amazon Nova Pro + catalog/routing tools)",
        epilog="AWS: uses the standard boto3 credential chain. With the project's IAM setup run "
        "AWS_PROFILE=nova-copilot python3 chat.py ... (region defaults to us-east-1; override with AWS_REGION). "
        "Model: NOVA_MODEL_ID, default us.amazon.nova-pro-v1:0 (the IAM policy allows only this inference profile).",
    )
    p.add_argument("question", nargs="*", help="Question; omit for interactive mode")
    p.add_argument("--trace", action="store_true", help="Print the tool calls")
    p.add_argument("--live", action="store_true",
                   help="Sign in with your AWS Builder ID and use the official live catalog and your schedule")
    p.add_argument("--profile", default=None,
                   help="Attendee profile name (stored locally in local-private/profiles/). Default: 'default'")
    a = p.parse_args()
    from atlas.env import load_dotenv
    load_dotenv()
    if a.profile:
        os.environ["ATLAS_PROFILE"] = a.profile
    if a.live:
        from atlas import official_auth
        official_auth.sign_in()
    agent = Agent(confirm=confirm_cli)
    if a.question:
        try:
            run_one(agent, " ".join(a.question), a.trace)
        except Exception as e:
            print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        return 0
    print("re:Invent Nova Copilot. Ask about sessions, routes or your day. 'reset' clears history, 'exit' quits.")
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        if q in ("exit", "quit"):
            return 0
        if q == "reset":
            agent.reset()
            continue
        try:
            run_one(agent, q, a.trace)
        except Exception as e:
            print(f"error: {type(e).__name__}: {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
