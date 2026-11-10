"""Amazon Nova Pro tool-use loop on the Bedrock Runtime Converse API.

Env: NOVA_MODEL_ID (default us.amazon.nova-pro-v1:0), AWS_REGION (default
us-east-1), AWS_PROFILE (optional, standard boto3 credential chain otherwise).
Write tools (add_favorites) run only if the `confirm` callback returns True.
The first request of every user turn sets toolChoice "any", so each answer reads the data through at
least one read tool; later rounds of the turn offer every tool with the default ("auto") so the model
can finish or, if asked, write.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from atlas.costs import append_usage
from atlas.prompts import SYSTEM_PROMPT
from atlas.tools import WRITE_TOOLS, Backend, bedrock_tool_config, dispatch

DEFAULT_MODEL_ID = "us.amazon.nova-pro-v1:0"
MAX_TOOL_ROUNDS = 6
INFERENCE_CONFIG = {"temperature": 0.3, "topP": 0.9, "maxTokens": 2000}
# Bedrock Converse ToolChoice: "any" = the model must request at least one tool.
FORCE_TOOL = {"any": {}}

ConfirmFn = Callable[[str, dict], bool]
_THINKING = re.compile(r"<thinking>.*?</thinking>", re.S)


@dataclass
class ToolCall:
    name: str
    input: dict
    ok: bool
    result: Any
    confirmed: bool | None = None  # None = not a write tool


@dataclass
class AgentResult:
    text: str
    trace: list[ToolCall] = field(default_factory=list)
    rounds: int = 0
    stop_reason: str = ""
    messages: list[dict] = field(default_factory=list)


def make_client(region: str | None = None, profile: str | None = None):
    import boto3

    session = boto3.Session(profile_name=profile or os.environ.get("AWS_PROFILE") or None)
    return session.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION") or "us-east-1")


# Tools that change something. The forced request leaves them out: live, "thanks" forced to call a tool
# picked add_favorites once and saved invented interests with update_profile once.
CHANGING_TOOLS = WRITE_TOOLS | {"update_profile"}


def _forced(config: dict) -> dict:
    """The forced request offers read tools only, so a turn never starts with a change."""
    reads = [t for t in config["tools"] if t["toolSpec"]["name"] not in CHANGING_TOOLS]
    return {**config, "tools": reads, "toolChoice": FORCE_TOOL}


def _text_of(content: list[dict]) -> str:
    text = "".join(b.get("text", "") for b in content if "text" in b)
    return _THINKING.sub("", text).strip()


class Agent:
    def __init__(
        self,
        client: Any = None,
        model_id: str | None = None,
        confirm: ConfirmFn | None = None,
        backend: Backend | None = None,
        max_rounds: int = MAX_TOOL_ROUNDS,
        system_prompt: str = SYSTEM_PROMPT,
        feature: str = "chat",
    ):
        self.client = client
        self.model_id = model_id or os.environ.get("NOVA_MODEL_ID") or DEFAULT_MODEL_ID
        self.confirm = confirm
        self.backend = backend
        self.max_rounds = max_rounds
        self.system_prompt = system_prompt
        self.feature = feature
        self.history: list[dict] = []

    def _converse(self, messages: list[dict], rounds: int = 0, force_tool: bool = False) -> dict:
        if self.client is None:
            self.client = make_client()
        config = bedrock_tool_config()

        def request(cfg: dict) -> dict:
            return self.client.converse(
                modelId=self.model_id,
                system=[{"text": self.system_prompt}],
                messages=messages,
                toolConfig=_forced(cfg) if force_tool else cfg,
                inferenceConfig=INFERENCE_CONFIG,
            )

        try:
            response = request(config)
        except Exception as e:
            # If the official MCP tool specs are what Bedrock rejected, drop them and retry once with our own tools.
            from atlas.tools import OFFICIAL_PREFIX, disable_official_tools

            if "Validation" not in type(e).__name__ + str(e) or not any(
                    t["toolSpec"]["name"].startswith(OFFICIAL_PREFIX) for t in config["tools"]):
                raise
            disable_official_tools()
            response = request(bedrock_tool_config())
        append_usage(self.model_id, self.feature, response.get("usage") or {}, rounds)
        return response

    def _run_tool(self, use: dict) -> tuple[dict, ToolCall]:
        name, args = use["name"], use.get("input") or {}
        confirmed = None
        if name in WRITE_TOOLS:
            confirmed = bool(self.confirm and self.confirm(name, args))
            if not confirmed:
                result, ok = {"error": "The attendee declined this change. Nothing was saved."}, False
                return self._result_block(use, result, ok), ToolCall(name, args, ok, result, confirmed)
        result, ok = dispatch(name, args, self.backend)
        return self._result_block(use, result, ok), ToolCall(name, args, ok, result, confirmed)

    @staticmethod
    def _result_block(use: dict, result: dict, ok: bool) -> dict:
        return {
            "toolResult": {
                "toolUseId": use["toolUseId"],
                "content": [{"text": json.dumps(result, ensure_ascii=False)}],
                "status": "success" if ok else "error",
            }
        }

    def ask(self, question: str) -> AgentResult:
        """One user turn. Keeps conversation history on the Agent for follow-ups."""
        messages = self.history + [{"role": "user", "content": [{"text": question}]}]
        trace: list[ToolCall] = []
        rounds = 0
        while True:
            resp = self._converse(messages, rounds, force_tool=rounds == 0)
            msg = resp["output"]["message"]
            messages.append(msg)
            stop = resp.get("stopReason", "")
            uses = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
            if uses and stop != "tool_use":
                # e.g. max_tokens mid tool call: do not run truncated args or keep a dangling toolUse.
                text = _text_of(msg["content"]) or f"The model stopped early ({stop}). Please ask again or narrow the question."
                messages[-1] = {"role": "assistant", "content": [{"text": text}]}
                self.history = messages
                return AgentResult(text, trace, rounds, stop, messages)
            if not uses:
                self.history = messages
                return AgentResult(_text_of(msg["content"]), trace, rounds, stop, messages)
            if rounds >= self.max_rounds:
                # Budget spent: answer the pending calls with an error and ask for a final answer.
                blocks = [self._result_block(u, {"error": "Tool budget used up. Answer now with the results you already have."}, False) for u in uses]
                messages.append({"role": "user", "content": blocks})
                resp = self._converse(messages, rounds)
                msg = resp["output"]["message"]
                if any("toolUse" in b for b in msg["content"]):
                    # Still asking for tools: do not keep a dangling toolUse in history.
                    text = "I could not finish within the tool budget. Please narrow the question."
                    return AgentResult(text, trace, rounds, resp.get("stopReason", ""), messages + [msg])
                messages.append(msg)
                self.history = messages
                text = _text_of(msg["content"]) or "I could not finish within the tool budget. Please narrow the question."
                return AgentResult(text, trace, rounds, resp.get("stopReason", ""), messages)
            rounds += 1
            blocks = []
            for use in uses:
                block, call = self._run_tool(use)
                blocks.append(block)
                trace.append(call)
            messages.append({"role": "user", "content": blocks})

    def reset(self) -> None:
        self.history = []


def ask(question: str, confirm: ConfirmFn | None = None, **kw: Any) -> AgentResult:
    return Agent(confirm=confirm, **kw).ask(question)
