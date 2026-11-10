"""Server-side shaping of Copilot answers for a narrow panel (M0 T4).

A safety net behind the prompt's response rules that never deletes model text: strip Markdown
symbols, append the plain "no additional session fits" sentence when the planner kept only the
reservations, and shorten a sentence that lists more than three dropped sessions to
"N dropped (3 shown: ...)", and append a note when the plan's day is not the weekday the attendee
named. Length is the prompt's job. Trace items are ToolCall objects or dicts.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

SHOWN_DROPPED = 3

_CJK_RE = re.compile("[぀-ヿ㐀-鿿豈-﫿]")
_END = re.compile(r"[.!?]+(?=[\s\"')\]]|$)|[。！？]+|\n")
_WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_WEEKDAY_ZH = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")

NO_ADDITION = "No additional session fits around your {base} on {day}."
NO_ADDITION_ZH = "{day}除了你的{base}，沒有其他場次排得進去。"
_NO_ADDITION_MARK = re.compile(r"\bno (?:other|additional|extra|more)\b[^.!?\n]{0,60}?\bsessions?\b[^.!?\n]{0,20}?\bfits?\b"
                               r"|沒有其他場次排得進去", re.I)


def _field(call: Any, key: str) -> Any:
    return call.get(key) if isinstance(call, dict) else getattr(call, key, None)


def _keys(row: dict) -> set[str]:
    return {k for k in (row.get("id"), row.get("code")) if isinstance(k, str) and k}


def _day_of(plan: dict, args: dict) -> int | None:
    day = (args.get("day") or plan.get("day") or "").strip().lower()
    abbr = {d[:3].lower(): i for i, d in enumerate(_WEEKDAY)}
    if day[:3] in abbr:
        return abbr[day[:3]]
    for value in [day] + [r.get("start") or "" for r in plan.get("chosen") or [] if isinstance(r, dict)]:
        try:
            return date.fromisoformat(value[:10]).weekday()
        except ValueError:
            continue
    return None


def _latest_plans(trace: list) -> list[tuple[dict, dict]]:
    """(result, input) of the latest successful plan_itinerary per day; a re-planned day counts once."""
    latest: dict = {}
    for call in trace or []:
        result, args = _field(call, "result"), _field(call, "input") or {}
        if _field(call, "name") == "plan_itinerary" and _field(call, "ok") and isinstance(result, dict) \
                and isinstance(result.get("plan"), dict):
            day = _day_of(result["plan"], args)
            latest.pop(day, None)
            latest[day] = (result, args)
    return list(latest.values())


def _is_cjk(text: str) -> bool:
    return len(_CJK_RE.findall(text)) > len(re.findall(r"[A-Za-z]+", text))


def strip_markdown(text: str) -> str:
    """Remove bold/italic asterisks, heading hashes, backticks and bullet markers."""
    if not text:
        return text
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]*", "", text)
    text = re.sub(r"(?m)^[ \t]*[*•\-][ \t]+", "", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?m)^[ \t]*\*[ \t]*$", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def no_addition_sentence(day: int | None, reservations: bool, cjk: bool = False) -> str:
    if cjk:
        return NO_ADDITION_ZH.format(day=_WEEKDAY_ZH[day] if day is not None else "這天",
                                     base="預約" if reservations else "必去場次")
    return NO_ADDITION.format(day=_WEEKDAY[day] if day is not None else "that day",
                              base="reservations" if reservations else "must-attend sessions")


_DAY_NAME = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day|s|sday|nesday|rs|rsday|urday)?\b|週([一二三四五六日])", re.I)


def _stated_days(text: str, n_plans: int) -> tuple[set[int], bool]:
    """Weekdays named in the answer's existing no-addition sentences, and whether one names no day
    (which covers the day only when a single plan was made)."""
    days, dayless = set(), False
    for m in _NO_ADDITION_MARK.finditer(text):
        start = max([b.end() for b in _END.finditer(text, 0, m.start())] or [0])
        nxt = _END.search(text, m.end())
        named = {[d[:3].lower() for d in _WEEKDAY].index(g[0].lower()) if g[0] else "一二三四五六日".index(g[1])
                 for g in _DAY_NAME.findall(text[start:nxt.end() if nxt else len(text)])}
        days, dayless = days | named, dayless or (not named and n_plans == 1)
    return days, dayless


def add_no_addition(text: str, trace: list) -> str:
    """Append the plain statement, one line per day whose latest plan kept only the reservations and
    must-attend sessions, unless an existing no-addition sentence already names that day. Nothing in
    the text is removed."""
    plans = _latest_plans(trace)
    if not text or not plans:
        return text
    stated, dayless = _stated_days(text, len(plans))
    lines = []
    for result, args in plans:
        base = {c for c in result.get("locked_from_schedule") or [] if isinstance(c, str)}
        must = {c for c in args.get("must") or [] if isinstance(c, str)}
        chosen = [r for r in result["plan"].get("chosen") or [] if isinstance(r, dict)]
        day = _day_of(result["plan"], args)
        if all(_keys(r) & (base | must) for r in chosen) and not dayless and day not in stated:
            lines.append(no_addition_sentence(day, bool(base), _is_cjk(text)))
    return "\n".join([text] + lines) if lines else text


def dropped_summary(n: int, shown: list[str], cjk: bool = False) -> str:
    shown = shown[:SHOWN_DROPPED]
    if cjk:
        return f"另有 {n} 場未排入（列出 {len(shown)} 場：{'、'.join(shown)}）"
    return f"{n} dropped ({len(shown)} shown: {', '.join(shown)})"


def collapse_dropped(text: str, trace: list) -> str:
    """In a sentence naming more than three dropped sessions, replace the run from the first to the
    last dropped code with "N dropped (3 shown: ...)"; the rest of the sentence stays, and a run that
    contains a planned session's code is left alone. Dropped means
    in a latest plan's dropped list and in no latest plan's chosen list ("not on <day>" rows are other
    days' candidates). N is the dropped count of the plan all codes in the run belong to; when the
    run mixes plans (days), N is the total over the latest plans."""
    plans = [r["plan"] for r, _ in _latest_plans(trace)]
    chosen = {k.upper() for p in plans for r in p.get("chosen") or [] if isinstance(r, dict) for k in _keys(r)}
    per_plan: list[dict[str, str]] = []
    for p in plans:
        rows = [r for r in p.get("dropped") or [] if isinstance(r, dict)
                and not str(r.get("reason") or "").startswith("not on ") and not {k.upper() for k in _keys(r)} & chosen]
        per_plan.append({k.upper(): r.get("code") or r.get("id") for r in rows for k in _keys(r)})
    label = {k: v for m in per_plan for k, v in m.items()}
    if not text or not label:
        return text
    alts = "|".join(re.escape(c) for c in sorted(label, key=len, reverse=True))
    pattern = re.compile(f"(?<![A-Za-z0-9-])(?:{alts})(?![A-Za-z0-9-])", re.I)
    total = len(set(label.values()))
    out, pos = [], 0
    for end in [m.end() for m in _END.finditer(text)] + [len(text)]:
        piece = text[pos:end]
        hits = list(pattern.finditer(piece))
        codes = list(dict.fromkeys(label[h.group(0).upper()] for h in hits))
        if len(codes) > SHOWN_DROPPED and not any(k in piece[hits[0].start():hits[-1].end()].upper() for k in chosen):
            owners = [p for p in per_plan if all(h.group(0).upper() in p for h in hits)]
            n = len(set(owners[0].values())) if len(owners) == 1 else total
            piece = piece[:hits[0].start()] + dropped_summary(n, codes, _is_cjk(piece)) + piece[hits[-1].end():]
        out.append(piece)
        pos = end
    return "".join(out)


DAY_MISMATCH = "Note: this plan is for {planned}, but you asked for {asked}."
DAY_MISMATCH_ZH = "注意：這份安排排的是{planned}，你問的是{asked}。"


def _day_label(iso: str, cjk: bool) -> str:
    i = date.fromisoformat(iso).weekday()
    return f"{_WEEKDAY_ZH[i]}（{iso}）" if cjk else f"{_WEEKDAY[i]} {iso}"


def add_day_mismatch(text: str, trace: list, question: str) -> str:
    """When the attendee named exactly one conference weekday and no latest plan covers that date,
    append one sentence naming the planned day(s) and the asked-for day. Nothing in the text is removed."""
    from atlas.tools import named_days

    asked = named_days(question)
    planned: set[str] = set()
    for result, _ in _latest_plans(trace):
        rows = result.get("days") if isinstance(result.get("days"), list) else [result]
        planned |= {r["day"] for r in rows if isinstance(r, dict) and isinstance(r.get("day"), str) and r.get("weekday")}
    if not text or len(asked) != 1 or not planned or asked[0] in planned:
        return text
    cjk = _is_cjk(text)
    sentence = (DAY_MISMATCH_ZH if cjk else DAY_MISMATCH).format(
        planned=("、" if cjk else " and ").join(_day_label(d, cjk) for d in sorted(planned)),
        asked=_day_label(asked[0], cjk))
    return text if sentence in text else f"{text}\n{sentence}"


def format_answer(text: str, trace: list | None = None, question: str = "") -> str:
    """All panel rules in order. Idempotent; removes nothing from the model's text but Markdown symbols."""
    trace = trace or []
    if not text:
        return text
    return add_day_mismatch(add_no_addition(collapse_dropped(strip_markdown(text), trace), trace), trace, question)
