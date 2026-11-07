"""Server-side shaping of Copilot answers so they fit a narrow panel (M0 T4).

Pure functions over the model's text and the tool trace (ToolCall objects or web.py's dict trace):
strip Markdown symbols, never claim added sessions the planner did not add, collapse long dropped
lists to "N dropped (3 shown: ...)", and cap answers at 160 words without cutting plan lines.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

MAX_WORDS = 160
SHOWN_DROPPED = 3

_CJK = "぀-ヿ㐀-鿿豈-﫿"
_CJK_RE = re.compile(f"[{_CJK}]")
_WORD = re.compile(f"[{_CJK}]|[^\\s{_CJK}]*[A-Za-z0-9][^\\s{_CJK}]*")
_END = re.compile(r"[.!?]+(?=[\s\"')\]]|$)|[。！？]+|\n")
_CLOCK = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
PLAN_LINE_MAX_WORDS = 30

_WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_ZH = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")
_DAY_ABBR = {d[:3].lower(): i for i, d in enumerate(_WEEKDAY)}

NO_ADDITION = "No additional session fits around your {base} on {day}."
NO_ADDITION_ZH = "{day}除了你的{base}，沒有其他場次排得進去。"
_NO_ADDITION_MARK = re.compile(r"\bno (?:other|additional|extra|more)\b[^.!?\n]{0,60}?\bsessions?\b[^.!?\n]{0,20}?\bfits?\b"
                               r"|沒有其他場次排得進去", re.I)
_CLAIM = re.compile(r"\b(?:added|adding|additions?|additional sessions?|extra sessions?|new sessions?)\b", re.I)
_CLAIM_ZH = re.compile(r"新增|加入了|加上了|額外|另外安排")
_NEGATION = re.compile(r"\b(?:no|not|nothing|none|cannot|without|never)\b|n't", re.I)
_NEGATION_ZH = re.compile(r"沒有|沒|無|不|未")


# ---- trace helpers -------------------------------------------------------------------------------

def _field(call: Any, key: str) -> Any:
    return call.get(key) if isinstance(call, dict) else getattr(call, key, None)


def _last_plan(trace: list) -> tuple[dict, dict] | None:
    """(tool result, tool input) of the last successful plan_itinerary call with a dict result."""
    for call in reversed(trace or []):
        result = _field(call, "result")
        if _field(call, "name") == "plan_itinerary" and _field(call, "ok") and isinstance(result, dict):
            if isinstance(result.get("plan"), dict):
                return result, _field(call, "input") or {}
    return None


def _keys(row: dict) -> set[str]:
    return {k for k in (row.get("id"), row.get("code")) if isinstance(k, str) and k}


def _label(row: dict) -> str:
    return row.get("code") or row.get("id") or ""


def _code_pattern(codes: set[str]) -> re.Pattern | None:
    codes = {c for c in codes if c}
    if not codes:
        return None
    alts = "|".join(re.escape(c) for c in sorted(codes, key=len, reverse=True))
    return re.compile(f"(?<![A-Za-z0-9-])(?:{alts})(?![A-Za-z0-9-])", re.I)


# ---- text helpers --------------------------------------------------------------------------------

def count_words(text: str) -> int:
    """Latin words plus CJK characters (each counts as one word)."""
    return len(_WORD.findall(text or ""))


def _pieces(line: str) -> list[str]:
    """Split one line into sentences; joining the pieces gives the line back."""
    out, pos = [], 0
    for m in _END.finditer(line):
        end = m.end()
        while end < len(line) and line[end] in " \t":
            end += 1
        if end > pos:
            out.append(line[pos:end])
            pos = end
    if pos < len(line):
        out.append(line[pos:])
    return out


def _is_cjk(text: str) -> bool:
    return len(_CJK_RE.findall(text)) > count_words(text) / 3


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---- 1. Markdown -----------------------------------------------------------------------------------

def strip_markdown(text: str) -> str:
    """Remove bold/italic asterisks, heading hashes, backticks and bullet markers."""
    if not text:
        return text
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*", "", text)
    text = re.sub(r"(?m)^[ \t]*[*•\-][ \t]+", "", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?m)^[ \t]*\*[ \t]*$", "", text)
    return _tidy(text)


# ---- 2. Honest "no additional session" -------------------------------------------------------------

def _day_of(plan: dict, args: dict) -> int | None:
    day = (args.get("day") or plan.get("day") or "").strip().lower()
    if day[:3] in _DAY_ABBR and not day[:1].isdigit():
        return _DAY_ABBR[day[:3]]
    for value in [day] + [r.get("start") or "" for r in plan.get("chosen") or []]:
        try:
            return date.fromisoformat(value[:10]).weekday()
        except ValueError:
            continue
    return None


def adds_nothing(trace: list) -> dict | None:
    """When the last plan keeps only the reservations (and must-attend sessions), the facts to say so."""
    found = _last_plan(trace)
    if not found:
        return None
    result, args = found
    plan = result["plan"]
    chosen = [r for r in plan.get("chosen") or [] if isinstance(r, dict)]
    locked = {c for c in result.get("locked_from_schedule") or [] if isinstance(c, str)}
    must = {c for c in args.get("must") or [] if isinstance(c, str)}
    base = locked | must
    if any(not (_keys(r) & base) for r in chosen):
        return None  # the planner added at least one session
    return {"day": _day_of(plan, args), "reservations": bool(locked)}


def no_addition_sentence(facts: dict, cjk: bool = False) -> str:
    i = facts.get("day")
    if cjk:
        base = "預約" if facts.get("reservations") else "必去場次"
        return NO_ADDITION_ZH.format(day=_WEEKDAY_ZH[i] if i is not None else "這天", base=base)
    base = "reservations" if facts.get("reservations") else "must-attend sessions"
    return NO_ADDITION.format(day=_WEEKDAY[i] if i is not None else "that day", base=base)


def _claims_addition(piece: str) -> bool:
    if _NO_ADDITION_MARK.search(piece):
        return False
    if _CLAIM.search(piece) and not _NEGATION.search(piece):
        return True
    return bool(_CLAIM_ZH.search(piece)) and not _NEGATION_ZH.search(piece)


def honest_additions(text: str, trace: list) -> str:
    """Replace claims of added sessions with the plain statement when the planner added none."""
    facts = adds_nothing(trace)
    if not text or facts is None:
        return text
    already = bool(_NO_ADDITION_MARK.search(text))  # the model said it plainly too: only drop the claims
    lines, replaced = [], False
    for line in text.split("\n"):
        kept = []
        for piece in _pieces(line):
            if not _claims_addition(piece):
                kept.append(piece)
            elif not replaced and not already:
                cjk = _is_cjk(piece)
                kept.append(no_addition_sentence(facts, cjk) + ("" if cjk else " "))
                replaced = True
            else:
                replaced = True
        lines.append("".join(kept).rstrip())
    return _tidy("\n".join(lines)) if replaced else text


# ---- 3. Dropped lists ------------------------------------------------------------------------------

def dropped_summary(n: int, shown: list[str], cjk: bool = False) -> str:
    shown = shown[:SHOWN_DROPPED]
    if cjk:
        return f"另有 {n} 場未排入（列出 {len(shown)} 場：{'、'.join(shown)}）。"
    return f"{n} dropped ({len(shown)} shown: {', '.join(shown)})."


_REASON = re.compile(r"^[\s,;:\-–]*(?:because|since|due to|as they|as both|which|that)\b|^[\s，、]*(?:因為|由於)", re.I)


def _summary_keeping_reason(piece: str, pattern: re.Pattern, summary: str) -> str:
    """The summary, plus the reason clause that followed the listed codes ("... because they overlap ...")."""
    last = None
    for last in pattern.finditer(piece):
        pass
    tail = piece[last.end():] if last else ""
    trailing = " " if piece.endswith((" ", "\t")) else ""
    if tail.strip() and _REASON.match(tail):
        clause = re.sub(r"^[\s,;:\-–，、]+", "", tail).rstrip()
        sep = "，" if summary.endswith("。") else " "
        return summary[:-1] + sep + clause + trailing
    return summary + trailing


def collapse_dropped(text: str, trace: list) -> str:
    """Collapse sentences or runs of lines that list more than three dropped sessions."""
    found = _last_plan(trace)
    if not text or not found:
        return text
    plan = found[0]["plan"]
    dropped_rows = [r for r in plan.get("dropped") or [] if isinstance(r, dict)]
    chosen_keys = {k.upper() for r in plan.get("chosen") or [] if isinstance(r, dict) for k in _keys(r)}
    label = {}
    for r in dropped_rows:
        for k in _keys(r):
            if k.upper() not in chosen_keys:
                label[k.upper()] = _label(r)
    pattern = _code_pattern(set(label))
    if pattern is None:
        return text
    n = len({_label(r) for r in dropped_rows})

    def mentioned(s: str) -> list[str]:
        out = []
        for m in pattern.finditer(s):
            code = label[m.group(0).upper()]
            if code not in out:
                out.append(code)
        return out

    chosen_pattern = _code_pattern(chosen_keys)
    any_pattern = _code_pattern(set(label) | chosen_keys)

    def n_chosen(s: str) -> int:
        return len({m.group(0).upper() for m in chosen_pattern.finditer(s)}) if chosen_pattern else 0

    def about_dropped(line: str) -> bool:
        # a dropped-list line starts with a dropped code; its reason may name a chosen or reserved one
        first = any_pattern.search(line)
        return bool(first and first.group(0).upper() in label)

    # sentences inside a line
    lines = []
    for line in text.split("\n"):
        pieces = []
        for piece in _pieces(line):
            codes = mentioned(piece)
            if len(codes) > SHOWN_DROPPED and len(codes) > n_chosen(piece):
                piece = _summary_keeping_reason(piece, pattern, dropped_summary(n, codes, _is_cjk(piece)))
            pieces.append(piece)
        lines.append("".join(pieces))

    # runs of lines that each list dropped sessions (one per line), with an optional header line
    out, i = [], 0
    while i < len(lines):
        j, codes = i, []
        while j < len(lines) and about_dropped(lines[j]):
            codes += [c for c in mentioned(lines[j]) if c not in codes]
            j += 1
        if j - i > 1 and len(codes) > SHOWN_DROPPED:
            if out and out[-1].rstrip().endswith((":", "：")) and not mentioned(out[-1]):
                out.pop()
            out.append(dropped_summary(n, codes, _is_cjk("\n".join(lines[i:j]))))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return _tidy("\n".join(out))


# ---- 4. Length -------------------------------------------------------------------------------------

def _is_plan_line(line: str, codes: re.Pattern | None) -> bool:
    if not line.strip() or count_words(line) > PLAN_LINE_MAX_WORDS:
        return False
    return bool(_CLOCK.search(line) or (codes and codes.search(line)))


def cap_words(text: str, trace: list | None = None, limit: int = MAX_WORDS) -> str:
    """Trim prose sentences until the answer has at most `limit` words.

    Plan lines (short lines with a clock time or a planned session code), the first sentence (the
    direct answer) and the "no additional session" sentence are never cut. Prose is trimmed from
    the end, keeping the closing next step for as long as possible.
    """
    if not text or count_words(text) <= limit:
        return text
    found = _last_plan(trace or [])
    chosen = {k for r in (found[0]["plan"].get("chosen") or []) if isinstance(r, dict) for k in _keys(r)} if found else set()
    codes = _code_pattern(chosen)
    lines = [_pieces(line) for line in text.split("\n")]
    removable: list[tuple[int, int]] = []
    first = True
    for li, pieces in enumerate(lines):
        line = "".join(pieces)
        if not line.strip():
            continue
        if _is_plan_line(line, codes):
            first = False
            continue
        for pi, piece in enumerate(pieces):
            if not piece.strip():
                continue
            if first:
                first = False
                continue
            if _NO_ADDITION_MARK.search(piece):
                continue
            removable.append((li, pi))
    order = removable[-2::-1] + removable[-1:]  # last sentence (next step) goes last
    total = count_words(text)
    for li, pi in order:
        if total <= limit:
            break
        total -= count_words(lines[li][pi])
        lines[li][pi] = ""
    return _tidy("\n".join("".join(p).rstrip() for p in lines))


# ---- pipeline --------------------------------------------------------------------------------------

def format_answer(text: str, trace: list | None = None, limit: int = MAX_WORDS) -> str:
    """All panel rules in order. Idempotent."""
    if not text:
        return text
    trace = trace or []
    text = strip_markdown(text)
    text = honest_additions(text, trace)
    text = collapse_dropped(text, trace)
    return cap_words(text, trace, limit)
