"""Server-side shaping of Copilot answers so they fit a narrow panel (M0 T4).

Pure functions over the model's text and the tool trace (ToolCall objects or web.py's dict trace):
strip Markdown symbols, never claim added sessions the planner did not add, collapse long dropped
lists to "N dropped (3 shown: ...)", and cap answers at 160 words without cutting plan lines
(a plan whose own lines exceed 160 words, e.g. eight sessions with all transitions, stays over).
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


def _plans(trace: list) -> list[tuple[dict, dict]]:
    """(tool result, tool input) of every successful plan_itinerary call with a dict result, in order."""
    out = []
    for call in trace or []:
        result = _field(call, "result")
        if _field(call, "name") == "plan_itinerary" and _field(call, "ok") and isinstance(result, dict) \
                and isinstance(result.get("plan"), dict):
            out.append((result, _field(call, "input") or {}))
    return out


def _planned_keys(trace: list) -> set[str]:
    """Ids and codes of sessions a tool placed in a plan or itinerary check."""
    keys: set[str] = set()
    for call in trace or []:
        result = _field(call, "result")
        if not (_field(call, "ok") and isinstance(result, dict)):
            continue
        if _field(call, "name") == "plan_itinerary" and isinstance(result.get("plan"), dict):
            rows = result["plan"].get("chosen") or []
        elif _field(call, "name") == "check_itinerary":
            rows = result.get("sessions") or []
        else:
            continue
        keys |= {k for r in rows if isinstance(r, dict) for k in _keys(r)}
    return keys


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


def _plan_facts(result: dict, args: dict) -> dict:
    """Day, whether the planner added sessions beyond the reservations and must-attend ones, and which."""
    plan = result["plan"]
    chosen = [r for r in plan.get("chosen") or [] if isinstance(r, dict)]
    locked = {c for c in result.get("locked_from_schedule") or [] if isinstance(c, str)}
    must = {c for c in args.get("must") or [] if isinstance(c, str)}
    added = [r for r in chosen if not (_keys(r) & (locked | must))]
    return {"day": _day_of(plan, args), "reservations": bool(locked),
            "added": {k for r in added for k in _keys(r)}, "adds_nothing": not added}


def adds_nothing(trace: list) -> dict | None:
    """When the last plan keeps only the reservations (and must-attend sessions), the facts to say so."""
    plans = _plans(trace)
    facts = _plan_facts(*plans[-1]) if plans else None
    return facts if facts and facts["adds_nothing"] else None


def no_addition_sentence(facts: dict, cjk: bool = False) -> str:
    i = facts.get("day")
    if cjk:
        base = "預約" if facts.get("reservations") else "必去場次"
        return NO_ADDITION_ZH.format(day=_WEEKDAY_ZH[i] if i is not None else "這天", base=base)
    base = "reservations" if facts.get("reservations") else "must-attend sessions"
    return NO_ADDITION.format(day=_WEEKDAY[i] if i is not None else "that day", base=base)


_SESSION_WORD = re.compile(r"\b(?:sessions?|workshops?|talks?|breakouts?|keynotes?|builders)\b", re.I)
_SESSION_WORD_ZH = re.compile(r"場|工作坊|講座")
_DAY_NAME = re.compile(r"\b(mon|tue|wed|thu|fri)(?:day|nesday|sday|rsday)?\b|(週[一二三四五])", re.I)
_ZH_DAY = {d: i for i, d in enumerate(_WEEKDAY_ZH)}


_SUGGESTION = re.compile(
    r"[?？]\s*$"  # a question offers, it does not claim
    r"|^(?:(?:next|then|tip|also|or)\s*[,:]\s*)?(?:(?:you|we|i)\s+(?:can|could|may|might|should)\b|would you|"
    r"do you want|want me|shall i|let me|search|look|find|consider|try|ask|check|browse|reserve|explore|add)\b"
    r"|^(?:下一步[:：]?\s*)?(?:可以|建議|要不要|試試|搜尋|找找)", re.I)


def _claims_addition(piece: str, codes: re.Pattern | None) -> bool:
    """A sentence that says sessions were added (not negated, and about sessions, not e.g. a profile)."""
    if _NO_ADDITION_MARK.search(piece) or _SUGGESTION.search(piece.strip()):
        return False
    about_session = bool(codes and codes.search(piece))
    if _CLAIM.search(piece) and not _NEGATION.search(piece):
        return about_session or bool(_SESSION_WORD.search(piece))
    if _CLAIM_ZH.search(piece) and not _NEGATION_ZH.search(piece):
        return about_session or bool(_SESSION_WORD_ZH.search(piece))
    return False


def _days_named(piece: str) -> set[int]:
    out = set()
    for m in _DAY_NAME.finditer(piece):
        out.add(_DAY_ABBR[m.group(1).lower()] if m.group(1) else _ZH_DAY[m.group(2)])
    return out


def honest_additions(text: str, trace: list) -> str:
    """Replace claims of added sessions with the plain statement for each plan that added none.

    With several plans in one answer (one per day), a claim is checked against the plan of the day it
    names; a claim that names a session the planner really added is kept.
    """
    facts = [_plan_facts(r, a) for r, a in _plans(trace)]
    latest = {}
    for f in facts:  # a day planned again counts with its latest plan only
        latest.pop(f["day"], None)
        latest[f["day"]] = f
    empty = [f for f in latest.values() if f["adds_nothing"]]
    if not text or not empty:
        return text
    added = _code_pattern({k for f in facts for k in f["added"]})
    sessions = _code_pattern(_planned_keys(trace) | {k for f in facts for k in f["added"]}
                             | {k for r, _ in _plans(trace) for d in r["plan"].get("dropped") or []
                                if isinstance(d, dict) for k in _keys(d)})
    empty_days = {f["day"]: f for f in empty}
    every_plan_empty = len(empty) == len(latest)
    already: set = set()  # days the model already stated plainly: only drop the claims there
    for line in text.split("\n"):
        for piece in _pieces(line):
            if _NO_ADDITION_MARK.search(piece):
                already |= (_days_named(piece) & set(empty_days)) or set(empty_days)
    said: set = set()
    lines, changed = [], False
    for line in text.split("\n"):
        kept = []
        for piece in _pieces(line):
            if not _claims_addition(piece, sessions) or (added and added.search(piece)):
                kept.append(piece)
                continue
            days = _days_named(piece)
            if days:
                hit = [empty_days[d] for d in sorted(days) if d in empty_days]
                if not hit or len(hit) < len(days):
                    kept.append(piece)  # names a day whose plan did add sessions
                    continue
            elif not every_plan_empty:
                kept.append(piece)  # cannot tell which day it means
                continue
            else:
                hit = [empty[-1]]
            changed = True
            cjk = _is_cjk(piece)
            for f in hit:
                if f["day"] in said or f["day"] in already:
                    continue
                said.add(f["day"])
                kept.append(no_addition_sentence(f, cjk) + ("" if cjk else " "))
        lines.append("".join(kept).rstrip())
    return _tidy("\n".join(lines)) if changed else text


# ---- 3. Dropped lists ------------------------------------------------------------------------------

def dropped_summary(n: int, shown: list[str], cjk: bool = False) -> str:
    shown = shown[:SHOWN_DROPPED]
    if cjk:
        return f"另有 {n} 場未排入（列出 {len(shown)} 場：{'、'.join(shown)}）。"
    return f"{n} dropped ({len(shown)} shown: {', '.join(shown)})."


_LIST_HEADER = re.compile(r"(?i)(?:\b(?:the planner |i )?dropped(?: sessions)?|未排入(?:的場次)?)\s*[:：]?\s*$")


def _collapse_span(piece: str, start: int, end: int, summary: str) -> str:
    """Replace piece[start:end] (a run of dropped codes) with the summary; the rest of the sentence
    (what to keep instead, the reason) stays. A "Dropped:" lead-in merges into the summary."""
    head, tail = piece[:start], piece[end:]
    head = _LIST_HEADER.sub("", head)
    core = summary[:-1]  # without the final period
    if not tail.strip():
        return head + summary + tail
    if summary.endswith("。") and not re.match(r"^\s*[，。、！？]", tail):
        tail = "，" + tail.lstrip(" ,;:，、")
    elif not summary.endswith("。"):
        tail = re.sub(r"^[\s,;:]+(?=\S)", " ", tail) if not re.match(r"^[.!?]", tail) else tail
    return head + core + tail


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

    def runs(piece: str) -> list[list[re.Match]]:
        # contiguous dropped codes; a planned (chosen) code between them ends the run
        out, cur = [], []
        for m in any_pattern.finditer(piece):
            if m.group(0).upper() in label:
                cur.append(m)
            else:
                out, cur = out + [cur] if cur else out, []
        return out + [cur] if cur else out

    # sentences inside a line
    lines = []
    for line in text.split("\n"):
        pieces = []
        for piece in _pieces(line):
            for run in reversed(runs(piece)):
                codes = list(dict.fromkeys(label[m.group(0).upper()] for m in run))
                if len(codes) > SHOWN_DROPPED:
                    piece = _collapse_span(piece, run[0].start(), run[-1].end(),
                                           dropped_summary(n, codes, _is_cjk(piece)))
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

FIRST_SENTENCE_MAX_WORDS = 40
_MINUTES = re.compile(r"\b\d+(?:\.\d+)?\s*(?:min|mins|minutes)\b|\d+\s*分鐘", re.I)


def _is_plan_line(line: str, codes: re.Pattern | None) -> bool:
    """A line naming a session the tools planned or checked, or a short line with a clock time or a
    travel time in minutes (leave the hotel, a transition, back to the hotel)."""
    if not line.strip():
        return False
    if codes and codes.search(line):
        return True
    return bool(_CLOCK.search(line) or _MINUTES.search(line)) and count_words(line) <= PLAN_LINE_MAX_WORDS


def _shorten(piece: str, words: int) -> str:
    kept = list(_WORD.finditer(piece))
    if len(kept) <= words:
        return piece
    return piece[:kept[words - 1].end()].rstrip(" ,;:，、") + "…"


def cap_words(text: str, trace: list | None = None, limit: int = MAX_WORDS) -> str:
    """Trim prose sentences until the answer has at most `limit` words.

    Plan lines (lines naming a session the tools planned or checked, and short lines with a clock
    time or travel minutes), the first sentence (the direct answer) and the "no additional session" sentence are kept.
    Prose is trimmed from the end, keeping the closing next step for as long as possible; then a first
    sentence longer than 40 words is shortened. Plan lines are never cut, so a plan whose own lines
    exceed the limit (eight sessions with all their transitions) stays over it.
    """
    if not text or count_words(text) <= limit:
        return text
    codes = _code_pattern(_planned_keys(trace or []))
    lines = [_pieces(line) for line in text.split("\n")]
    removable: list[tuple[int, int]] = []
    first_at: tuple[int, int] | None = None
    for li, pieces in enumerate(lines):
        line = "".join(pieces)
        if not line.strip():
            continue
        if _is_plan_line(line, codes):
            first_at = first_at or (-1, -1)
            continue
        for pi, piece in enumerate(pieces):
            if not piece.strip():
                continue
            if first_at is None:
                first_at = (li, pi)
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
    if total > limit and first_at and first_at[0] >= 0:
        li, pi = first_at
        lines[li][pi] = _shorten(lines[li][pi], FIRST_SENTENCE_MAX_WORDS)
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
