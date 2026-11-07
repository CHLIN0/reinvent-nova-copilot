import { ZONE, dayLabel, planLabel, planMark } from "./model.mjs";
import { sessionFacets } from "./session-facets.mjs";

const MINUTE = 60_000;
const clock = (minutes) =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
const identity = (record) => String(record.key ?? record.placement ?? "");
const valid = (record) =>
  Number.isFinite(record.times?.start) &&
  Number.isFinite(record.times?.end) &&
  record.times.end > record.times.start;
const ordered = (records) =>
  [...records].sort(
    (a, b) =>
      (a.times?.start ?? Infinity) - (b.times?.start ?? Infinity) ||
      String(a.session?.code || "").localeCompare(
        String(b.session?.code || ""),
      ) ||
      identity(a).localeCompare(identity(b)),
  );
const unique = (records) => [
  ...new Map(records.map((record) => [identity(record), record])).values(),
];

// Convert a venue-local midnight to an instant. Source intervals keep their
// explicit offsets; clipping must compare instants, never HH:mm strings.
export function dayBoundary(day) {
  const desired = Date.parse(`${day}T00:00:00Z`);
  if (!Number.isFinite(desired) || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return NaN;
  let instant = desired;
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (let pass = 0; pass < 3; pass += 1) {
    const p = Object.fromEntries(
      formatter.formatToParts(instant).map((part) => [part.type, part.value]),
    );
    const represented = Date.UTC(
      +p.year,
      +p.month - 1,
      +p.day,
      +p.hour,
      +p.minute,
      +p.second,
    );
    instant += desired - represented;
  }
  return instant;
}
function nextDay(day) {
  return new Date(Date.parse(`${day}T12:00:00Z`) + 86_400_000)
    .toISOString()
    .slice(0, 10);
}

/** Half-open hour buckets: each record starts once; continuing is separate. */
export function hourlySlots(records, day, firstHour = 480, lastHour = 1080) {
  const start = dayBoundary(day),
    end = dayBoundary(nextDay(day));
  const members = ordered(
    unique(records)
      .filter(valid)
      .filter((record) => record.times.start < end && record.times.end > start),
  );
  const slots = [];
  for (let hour = firstHour; hour <= lastHour; hour += 60) {
    const instant = start + hour * MINUTE,
      slotEnd = Math.min(instant + 60 * MINUTE, end);
    slots.push({
      hour,
      starts: members.filter(
        (record) =>
          record.times.start >= instant && record.times.start < slotEnd,
      ),
      ongoing: members.filter(
        (record) => record.times.start < instant && record.times.end > instant,
      ),
    });
  }
  return slots;
}

export function stackModel(records = [], days = []) {
  const distinct = unique(records),
    bounds = days.map((day) => ({
      day,
      start: dayBoundary(day),
      end: dayBoundary(nextDay(day)),
    }));
  let firstHour = 480,
    lastHour = 1080;
  for (const { start, end } of bounds) {
    for (const record of distinct.filter(valid)) {
      if (record.times.start >= end || record.times.end <= start) continue;
      firstHour = Math.min(
        firstHour,
        Math.floor(
          (Math.max(start, record.times.start) - start) / (60 * MINUTE),
        ) * 60,
      );
      lastHour = Math.max(
        lastHour,
        Math.ceil((Math.min(end, record.times.end) - start) / (60 * MINUTE)) *
          60 -
          60,
      );
    }
  }
  const hours = [];
  for (let hour = firstHour; hour <= lastHour; hour += 60) hours.push(hour);
  return {
    firstHour,
    lastHour,
    hours,
    days: bounds.map(({ day, start, end }) => {
      const members = distinct
        .filter(valid)
        .filter(
          (record) => record.times.start < end && record.times.end > start,
        );
      return {
        day,
        total: members.length,
        starts: members.filter((record) => record.times.start >= start).length,
        continuingFromEarlierDay: members.filter(
          (record) => record.times.start < start,
        ).length,
        slots: hourlySlots(members, day, firstHour, lastHour),
      };
    }),
    untimed: distinct.filter((record) => !valid(record)),
  };
}

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = String(text);
  return el;
}
function timeRange(record) {
  if (!valid(record)) return "時間待公布";
  const formatter = new Intl.DateTimeFormat("zh-TW", {
    timeZone: ZONE,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const minutes = Math.round((record.times.end - record.times.start) / MINUTE);
  return `${formatter.format(record.times.start)} – ${formatter.format(record.times.end)} · ${minutes} 分鐘`;
}
function location(record) {
  return (
    record.session?.location ||
    record.session?.venue ||
    record.venue?.name ||
    "場地待公布"
  );
}
function label(value) {
  return typeof value === "string"
    ? value
    : String(value?.label || value?.name || value?.id || "");
}
const sourceFieldLabels = {
  title: "標題",
  abstract: "摘要",
  tags: "官方標籤",
  speakers: "講者",
};
/** Human-readable projection of public classification evidence, kept separate by origin. */
export function comparisonProvenance(record, taxonomy = []) {
  const session = record.session || {};
  const topics = new Map(
    taxonomy.map((topic) => [topic.id, topic.label || topic.id]),
  );
  const topicLabel = (value) =>
    topics.get(typeof value === "string" ? value : value?.id) || label(value);
  const official =
    record.officialFacets ||
    sessionFacets(session, taxonomy).filter((facet) =>
      facet.sources?.includes("official"),
    );
  const matches = session.derived_company_matches || [];
  const reasons = Array.isArray(session.classification_reasons)
    ? session.classification_reasons
    : [];
  const evidence = [];
  for (const reason of reasons) {
    if (typeof reason === "string") {
      evidence.push(reason);
      continue;
    }
    const heading =
      reason.label || topics.get(reason.id) || reason.id || "系統分類";
    if (reason.reason) evidence.push(`${heading}：${reason.reason}`);
    for (const detail of Array.isArray(reason.evidence)
      ? reason.evidence
      : []) {
      if (typeof detail === "string") evidence.push(`${heading} · ${detail}`);
      else if (detail && (detail.excerpt || detail.match))
        evidence.push(
          `${heading} · ${sourceFieldLabels[detail.field] || detail.field || "公開文字"}：「${detail.excerpt || detail.match}」`,
        );
    }
  }
  for (const match of matches)
    if (match.excerpt || match.match)
      evidence.push(
        `${label(match.company || match)} · ${sourceFieldLabels[match.field] || match.field || "公開文字"}：「${match.excerpt || match.match}」`,
      );
  return {
    official: official.map((facet) => facet.label),
    system: (session.system_topics || []).map(topicLabel),
    companies: matches.map((match) => label(match.company || match)),
    evidence,
  };
}

function sourceGroup(card, name, labels, kind) {
  if (!labels.length) return;
  const group = node("div", "atlas-stack-provenance");
  group.append(node("p", "atlas-stack-provenance-label", name));
  const chips = node("div", "atlas-stack-chips");
  for (const text of [...new Set(labels.filter(Boolean))])
    chips.append(
      node("span", `atlas-stack-chip atlas-stack-chip-${kind}`, text),
    );
  group.append(chips);
  card.append(group);
}

/** Nothing touches the DOM until this factory is called. */
export function createStackCalendar({ container, onSelect = () => {} }) {
  let records = [],
    days = [],
    selection = null,
    plan = [],
    taxonomy = [],
    dialog = null,
    trigger = null,
    destroyed = false;
  const triggers = new Map(),
    groups = new Map();
  const root = node("div", "atlas-stack");
  container.append(root);
  function closeComparison(restoreFocus = true) {
    const old = dialog,
      previousTrigger = trigger;
    dialog = null;
    trigger = null;
    if (previousTrigger?.isConnected)
      previousTrigger.setAttribute("aria-expanded", "false");
    if (old) {
      if (old.open) old.close();
      old.remove();
    }
    if (restoreFocus && previousTrigger?.isConnected)
      previousTrigger.focus({ preventScroll: true });
  }
  function openComparison(members, opener, heading, explanation) {
    closeComparison(false);
    trigger = opener;
    opener.setAttribute("aria-expanded", "true");
    dialog = node("dialog", "atlas-stack-dialog");
    const activeDialog = dialog;
    const titleId = `atlas-stack-dialog-title-${Math.random().toString(36).slice(2)}`;
    dialog.setAttribute("aria-labelledby", titleId);
    const header = node("header", "atlas-stack-dialog-header");
    const headingNode = node("h2", "", heading);
    headingNode.id = titleId;
    const close = node("button", "atlas-stack-dialog-close", "關閉比較");
    close.type = "button";
    close.addEventListener("click", () => closeComparison());
    header.append(headingNode, close);
    const intro = node("p", "atlas-stack-dialog-intro", explanation);
    const grid = node("div", "atlas-stack-comparison");
    const planned = new Map(plan.map((item) => [item.placement, item]));
    for (const original of ordered(members)) {
      const card = node("article", "atlas-stack-comparison-card");
      card.dataset.placement = original.placement;
      if (identity(original) === selection) card.classList.add("is-selected");
      card.append(
        node("p", "atlas-stack-code", original.session?.code || "公開議程"),
        node("h3", "", original.session?.title || "未命名議程"),
        node(
          "p",
          "atlas-stack-full-time",
          `${timeRange(original)} · 拉斯維加斯時間`,
        ),
        node("p", "atlas-stack-venue", location(original)),
      );
      if (planned.has(original.placement))
        card.append(
          node(
            "p",
            "atlas-stack-local-plan",
            planLabel(planned.get(original.placement)),
          ),
        );
      const provenance = comparisonProvenance(original, taxonomy);
      sourceGroup(card, "官方原始標籤", provenance.official, "official");
      sourceGroup(card, "系統推導主題", provenance.system, "system");
      sourceGroup(
        card,
        "公司文字關聯 · 不代表贊助、任職或出席",
        provenance.companies,
        "company",
      );
      if (provenance.evidence.length) {
        const evidence = node("details", "atlas-stack-evidence");
        evidence.append(node("summary", "", "公開文字分類依據"));
        for (const text of provenance.evidence)
          evidence.append(node("p", "", text));
        card.append(evidence);
      }
      const read = node("button", "atlas-stack-read", "完整摘要");
      read.type = "button";
      read.addEventListener("click", () => {
        closeComparison(false);
        onSelect(original.key);
      });
      card.append(read);
      grid.append(card);
    }
    dialog.append(header, intro, grid);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeComparison();
    });
    dialog.addEventListener("close", () => {
      if (dialog === activeDialog) closeComparison();
    });
    document.body.append(dialog);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    close.focus({ preventScroll: true });
  }
  function stack(members, day, hour, ongoing = false, untimed = false) {
    const single = members.length === 1;
    const button = node(
      "button",
      ongoing ? "atlas-stack-ongoing" : "atlas-stack-trigger",
    );
    button.dataset.stackGroup = untimed
      ? "untimed"
      : `${day}|${hour}|${ongoing ? "ongoing" : "starts"}`;
    button.dataset.firstRecord = identity(members[0]);
    groups.set(button.dataset.stackGroup, button);
    button.type = "button";
    if (!single) {
      button.setAttribute("aria-haspopup", "dialog");
      button.setAttribute("aria-expanded", "false");
    }
    if (members.some((record) => identity(record) === selection))
      button.classList.add("is-selected");
    if (ongoing) {
      button.append(
        node("strong", "", `${members.length} 場仍在進行`),
        node("span", "", "於此時段之前開始 · 核對完整起訖"),
      );
      if (single) button.append(node("span", "atlas-stack-hint", "完整摘要 ↗"));
    } else {
      button.append(
        node(
          "span",
          "atlas-stack-topline",
          untimed ? "時間待公布" : `${clock(hour)}–${clock(hour + 60)} 開始`,
        ),
      );
      button.append(
        node("strong", "atlas-stack-count", `${members.length} 場`),
      );
      const planned = new Map(plan.map((item) => [item.placement, item]));
      for (const record of members.slice(0, 2)) {
        const item = planned.get(record.placement);
        const preview = node(
          "span",
          "atlas-stack-preview-title",
          `${planMark(item)}${record.session?.code ? record.session.code + " · " : ""}${record.session?.title || "未命名議程"}`,
        );
        if (item) preview.classList.add("plan-" + item.source);
        button.append(preview);
      }
      // Every planned session in the group is counted, including ones beyond the two previews.
      const inPlan = members
        .map((record) => planned.get(record.placement))
        .filter(Boolean);
      if (inPlan.length)
        button.append(
          node(
            "span",
            "atlas-stack-local-plan",
            ["reserved", "favorite", "local"]
              .map((source) => [source, inPlan.filter((i) => i.source === source).length])
              .filter(([, n]) => n)
              .map(([source, n]) => `${planMark({ source })}${planLabel({ source })} ${n}`)
              .join(" · "),
          ),
        );
      if (!untimed)
        button.append(
          node("span", "atlas-stack-preview-time", timeRange(members[0])),
        );
      button.append(
        node(
          "span",
          "atlas-stack-hint",
          single ? "完整摘要 ↗" : `比較 ${members.length} 場 ↗`,
        ),
      );
    }
    const title = untimed
      ? `${members.length} 場時間待公布`
      : `${dayLabel(day)} ${clock(hour)} · ${members.length} 場${ongoing ? "仍在進行" : "開始"}`;
    button.setAttribute(
      "aria-label",
      `${title}。${ongoing ? "這些議程於較早時段開始。" : ""}${single ? "閱讀完整摘要" : "開啟議程比較"}`,
    );
    button.addEventListener("click", () => {
      if (single) {
        closeComparison(false);
        onSelect(members[0].key);
        return;
      }
      openComparison(
        members,
        button,
        title,
        ongoing
          ? "以下議程在較早時段開始，目前仍在進行；請核對各場完整起訖。"
          : "按開始時間排序；卡疊的高度不代表議程長度。以下包含此組全部議程，可捲動閱讀與比較。",
      );
    });
    for (const record of members)
      if (!triggers.has(identity(record)))
        triggers.set(identity(record), button);
    return button;
  }
  function render() {
    triggers.clear();
    groups.clear();
    root.replaceChildren();
    const model = stackModel(records, days);
    root.append(
      node(
        "p",
        "atlas-stack-guide",
        "開始時段 · 每列是一小時內開始的議程，卡疊高度不代表時長；「仍在進行」另列提示，不重複計入每日場數。",
      ),
    );
    const scroll = node("div", "atlas-stack-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute(
      "aria-label",
      "議程卡疊行事曆；可上下及左右捲動，時間為拉斯維加斯當地時間",
    );
    const grid = node("div", "atlas-stack-grid");
    grid.style.setProperty(
      "--atlas-stack-days",
      String(Math.max(1, days.length)),
    );
    const corner = node("div", "atlas-stack-corner", "拉斯維加斯\n開始時段");
    corner.style.gridColumn = "1";
    corner.style.gridRow = "1";
    grid.append(corner);
    model.hours.forEach((hour, index) => {
      const ruler = node("div", "atlas-stack-ruler");
      ruler.append(
        node("strong", "", clock(hour)),
        node("small", "", `至 ${clock(hour + 60)}`),
      );
      ruler.style.gridColumn = "1";
      ruler.style.gridRow = String(index + 2);
      grid.append(ruler);
    });
    model.days.forEach((day, index) => {
      const header = node("header", "atlas-stack-day-header");
      header.style.gridColumn = String(index + 2);
      header.style.gridRow = "1";
      header.append(
        node("h3", "", dayLabel(day.day)),
        node(
          "p",
          "",
          `${day.total} 場${day.continuingFromEarlierDay ? ` · 含 ${day.continuingFromEarlierDay} 場前日延續` : ""}`,
        ),
      );
      grid.append(header);
      day.slots.forEach((slot, row) => {
        const cell = node("div", "atlas-stack-cell");
        cell.style.gridColumn = String(index + 2);
        cell.style.gridRow = String(row + 2);
        cell.dataset.day = day.day;
        cell.dataset.hour = clock(slot.hour);
        if (slot.starts.length)
          cell.append(stack(slot.starts, day.day, slot.hour));
        if (slot.ongoing.length)
          cell.append(stack(slot.ongoing, day.day, slot.hour, true));
        if (!slot.starts.length && !slot.ongoing.length)
          cell.append(node("span", "atlas-stack-empty", "—"));
        grid.append(cell);
      });
    });
    scroll.append(grid);
    root.append(scroll);
    if (model.untimed.length) {
      const extra = node("section", "atlas-stack-untimed");
      extra.append(
        node("h3", "", "時間待公布"),
        stack(model.untimed, null, null, false, true),
      );
      root.append(extra);
    }
  }
  return {
    update(next = {}) {
      if (destroyed) return;
      const sameDays =
        days.length === (next.days || []).length &&
        days.every((day, index) => day === next.days[index]);
      const nextSelection =
        typeof next.selection === "string"
          ? next.selection
          : next.selection?.key || null;
      const sameRecords =
        records.length === (next.records || []).length &&
        records.every((record, index) => record === next.records[index]);
      // A plan refresh must not dismiss the comparison being read. Real catalog,
      // selection or filter changes still invalidate its candidate group.
      if (
        dialog?.open &&
        sameDays &&
        sameRecords &&
        selection === nextSelection
      ) {
        plan = next.plan || [];
        const planned = new Map(plan.map((item) => [item.placement, item]));
        for (const card of dialog.querySelectorAll(
          ".atlas-stack-comparison-card",
        )) {
          const note = card.querySelector(".atlas-stack-local-plan");
          const item = planned.get(card.dataset.placement);
          if (item && note) note.textContent = planLabel(item);
          else if (item)
            card.append(node("p", "atlas-stack-local-plan", planLabel(item)));
          else note?.remove();
        }
        return;
      }
      const oldScroll = root.querySelector(".atlas-stack-scroll");
      const savedScroll =
        sameDays && oldScroll
          ? { top: oldScroll.scrollTop, left: oldScroll.scrollLeft }
          : null;
      // A stale dialog is closed by update. Restore its calendar opener only
      // when focus still belonged to that dialog, never steal sidebar focus.
      const active = document.activeElement;
      const focused = root.contains(active)
        ? active
        : dialog?.contains(active) && root.contains(trigger)
          ? trigger
          : null;
      const focusGroup = focused?.dataset.stackGroup;
      const focusRecord = focused?.dataset.firstRecord;
      const focusScroll = focused === oldScroll;
      closeComparison(false);
      records = next.records || [];
      days = [...(next.days || [])];
      selection =
        typeof next.selection === "string"
          ? next.selection
          : next.selection?.key || null;
      plan = next.plan || [];
      taxonomy = next.taxonomy || [];
      render();
      if (sameDays) {
        const scroll = root.querySelector(".atlas-stack-scroll");
        const target =
          groups.get(focusGroup) ||
          triggers.get(focusRecord) ||
          (focusScroll ? scroll : null);
        target?.focus({ preventScroll: true });
        if (savedScroll) {
          scroll.scrollTop = savedScroll.top;
          scroll.scrollLeft = savedScroll.left;
        }
      }
    },
    scrollToRecord(key) {
      const button = triggers.get(String(key));
      if (!button) return false;
      button.scrollIntoView({
        block: "nearest",
        inline: "nearest",
        behavior: "auto",
      });
      return true;
    },
    compare(members, title = "同時段議程", opener = document.activeElement) {
      if (destroyed || !members?.length) return;
      openComparison(
        unique(members),
        opener || document.activeElement,
        title,
        "以下包含此組全部議程，按開始時間排序；可捲動閱讀與比較。",
      );
    },
    closeComparison,
    destroy() {
      closeComparison(false);
      destroyed = true;
      triggers.clear();
      groups.clear();
      root.remove();
    },
  };
}
