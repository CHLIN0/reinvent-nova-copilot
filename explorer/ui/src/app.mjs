import "temporal-polyfill/global";
import { Calendar } from "fullcalendar";
import timeGridPlugin from "fullcalendar/timegrid";
import themePlugin from "fullcalendar/themes/monarch";
import zhTW from "fullcalendar/locales/zh-tw";
import "fullcalendar/skeleton.css";
import "fullcalendar/themes/monarch/theme.css";
import "fullcalendar/themes/monarch/palettes/blue.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";
import "./calendar-stack.css";
import { createStackCalendar } from "./calendar-stack.mjs";
import { createFilterControls } from "./filter-controls.mjs";
import {
  enrichRecords,
  normaliseFilters,
  normaliseCalendarFilters,
  filterDiscovery,
  DISCOVERY_DIMENSIONS,
} from "./discovery.mjs";
import { createScene, VENUES } from "./scene.mjs";
import { createPlanStore, watchPlan, PLAN_CHANGED } from "./plan-store.mjs";
import {
  seatText,
  planButtonText as planButtonLabel,
  planToggleDisabled as planToggleOff,
  cancelConfirmText,
  cancelResultText,
  cancelReservation,
} from "./rsvp.mjs";
import { serviceErrorText } from "./service-errors.mjs";
import {
  homeDay,
  dayAgenda,
  dayCounts,
  createHomeChoice,
  createCalendarSync,
} from "./my-day.mjs";
import {
  createOfficialConnection,
  connectionCopy,
  catalogFailureMessage,
  sourceTimingNote,
  AUTH_STATUS_EVENT,
} from "./official-connection.mjs";
import {
  ZONE,
  DAYS,
  prepare,
  inDay,
  dayForSelection,
  dayLabel,
  localDate,
  localClock,
  makePlanItem,
  planLabel,
  planMark,
  abstractHash,
  validateCatalog,
  observationLabel,
} from "./model.mjs";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const button = (label, action, cls = "") => {
  const b = el("button", cls, label);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
};
// The plan lives on the server (/api/plan); filters live in the URL hash only.
const planStore = createPlanStore();
const SIGN_IN_RETURN_KEY = "event-atlas.sign-in-return.v1";
// Coming back from sign-in always opens My re:Invent, whatever tab started the sign-in.
const returnedFromSignIn =
  new URLSearchParams(location.search).get("signin") === "complete";
// This stores only the current calendar view, never an authorization URL or token.
if (returnedFromSignIn) {
  let savedHash = "";
  try {
    savedHash = sessionStorage.getItem(SIGN_IN_RETURN_KEY) || "";
    sessionStorage.removeItem(SIGN_IN_RETURN_KEY);
  } catch {}
  history.replaceState(
    null,
    "",
    location.pathname + (savedHash.startsWith("#") ? savedHash : location.hash),
  );
}
const FILTER_DIMENSIONS = DISCOVERY_DIMENSIONS.filter((key) => key !== "dates");
const state = {
  ...normaliseCalendarFilters({}),
  view: "week",
  layout: "stack",
  // "mine" (My re:Invent) or "explore"; null until the sign-in state is known.
  tab: null,
  day: DAYS[0],
  panel: "none",
  selection: null,
  spotlight: null,
  planOnly: false,
  plan: [],
};
let records = [],
  byKey = new Map(),
  translations = [],
  meta = {},
  catalogReady = false,
  scene = null,
  readerVersion = 0,
  weekScroll = null,
  dayScroll = null;
let requestedTab = null,
  dayFromURL = false;
let planUnavailable = true,
  planError = "";
const notify = (message) => {
  $("notice").textContent = message;
  $("notice").hidden = !message;
};
try {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of ["view", "day", "layout", "selection"])
    if (p.has(k)) state[k] = p.get(k);
  // A reload of My re:Invent keeps its day; a fresh open or a sign-in return starts on the home day.
  dayFromURL = p.has("day") && p.has("tab") && !returnedFromSignIn;
  if (p.has("tab") && !returnedFromSignIn) requestedTab = p.get("tab");
  if (p.has("filters")) {
    const restored = {
      query: p.get("query") || "",
      from: p.get("from") || "",
      to: p.get("to") || "",
    };
    for (const k of FILTER_DIMENSIONS) restored[k] = p.getAll(k);
    Object.assign(state, normaliseCalendarFilters(restored));
  }
  if (!DAYS.includes(state.day)) state.day = DAYS[0];
  if (!["week", "day"].includes(state.view)) state.view = "week";
  if (!["stack", "overlap", "columns"].includes(state.layout))
    state.layout = "stack";
} catch {}
if (state.selection) state.panel = "abstract";
else if (state.view === "day" && requestedTab === "explore") state.panel = "map";
function writeURL() {
  const p = new URLSearchParams({
    view: state.view,
    day: state.day,
    layout: state.layout,
    filters: "1",
  });
  // An Explore the page fell back to (signed out, failed check) is not saved, so it never blocks
  // My re:Invent on reload.
  const tab = state.tab && homeChoice.urlTab;
  if (tab) p.set("tab", tab);
  for (const k of ["query", "from", "to", "selection"])
    if (state[k]) p.set(k, state[k]);
  for (const k of FILTER_DIMENSIONS)
    for (const value of state[k]) p.append(k, value);
  history.replaceState(null, "", "#" + p);
}

function scrollPane() {
  return [...$("calendar").querySelectorAll("*")].find(
    (n) =>
      n.scrollHeight > n.clientHeight + 20 &&
      getComputedStyle(n).overflowY === "auto",
  );
}
function captureScroll() {
  const pane = scrollPane();
  if (pane) {
    if (state.view === "week") weekScroll = pane.scrollTop;
    else dayScroll = pane.scrollTop;
  }
}
function restoreScroll() {
  requestAnimationFrame(() => {
    const pane = scrollPane();
    const saved = state.view === "week" ? weekScroll : dayScroll;
    if (pane && saved !== null) pane.scrollTop = saved;
  });
}
function filtered() {
  return filterDiscovery(records, state, state.plan);
}
function visible() {
  const result = filtered();
  return state.view === "day"
    ? result.filter((r) => inDay(r, state.day))
    : result.filter((r) => DAYS.some((day) => inDay(r, day)));
}
function planItem(r) {
  return state.plan.find((p) => p.placement === r.placement);
}
function isPlanned(r) {
  return !!planItem(r);
}
// Server items carry the session id; use the loaded record's own placement so marks always line up.
function canonicalPlan(items) {
  const byId = new Map(records.map((r) => [r.session.session_id, r]));
  return items.map((p) => {
    const r = byId.get(p.session_id);
    return r ? { ...p, placement: r.placement, key: r.key } : p;
  });
}
function planButtonText(r) {
  return planButtonLabel(planItem(r));
}
function planToggleDisabled(r) {
  return planToggleOff(planItem(r), planUnavailable);
}
function planNoteText(r) {
  return planItem(r)?.source === "reserved"
    ? "✓ 官方已預約。取消會送到 AWS Events，並重新讀取官方行程確認。"
    : "只修改本機安排，不提交 RSVP；可以保留重疊。";
}
function timeText(r) {
  return r.times
    ? `${dayLabel(r.date)} · ${localClock(r.session.start_local)}–${localClock(r.session.end_local)}`
    : "時間尚未完整公布";
}
function selectedRecord() {
  return byKey.get(state.selection);
}
const calendar = new Calendar($("calendar"), {
  plugins: [themePlugin, timeGridPlugin],
  locale: zhTW,
  timeZone: ZONE,
  firstDay: 1,
  initialDate: state.view === "day" ? state.day : DAYS[0],
  initialView: state.view === "day" ? "timeGridDay" : "fiveDays",
  views: {
    fiveDays: {
      type: "timeGrid",
      duration: { days: 5 },
      dateAlignment: "week",
      firstDay: 1,
      eventMaxStack: 6,
    },
    timeGridDay: { eventMaxStack: 8 },
  },
  headerToolbar: false,
  allDaySlot: false,
  height: "100%",
  slotMinTime: "00:00:00",
  slotMaxTime: "24:00:00",
  scrollTime: "08:00:00",
  scrollTimeReset: false,
  slotDuration: "00:30:00",
  slotHeaderInterval: "01:00:00",
  slotMinHeight: 40,
  slotHeaderFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
  dayHeaderFormat: { weekday: "short", month: "numeric", day: "numeric" },
  navLinks: true,
  navLinkDayClick: (date) => changeView("day", localDate(date)),
  nowIndicator: false,
  editable: false,
  selectable: false,
  eventInteractive: true,
  eventMinHeight: 20,
  slotEventOverlap: state.layout === "overlap",
  eventOrder: "_rank,start,-duration,title",
  eventOrderStrict: true,
  eventClick: (info) => select(info.event.id),
  eventContent: (info) => {
    const r = byKey.get(info.event.id);
    if (!r) return { domNodes: [] };
    const n = el("div", "agenda-card");
    n.append(
      el("span", "event-code", `${planMark(planItem(r))}${r.session.code}`),
      el(
        "span",
        "event-time",
        `${localClock(r.session.start_local)}–${localClock(r.session.end_local)}`,
      ),
      el("strong", "event-title", r.session.title),
      el(
        "span",
        "event-venue",
        r.venue?.name || r.session.venue || "會場未定位",
      ),
    );
    const chips = el("div", "event-tags");
    const topics = r.systemTopics
      .slice(0, 1)
      .map((id) => meta.taxonomy?.find((t) => t.id === id)?.label || id);
    for (const tag of [...r.companies, ...topics].slice(0, 2))
      chips.append(el("span", "", tag));
    if (chips.childElementCount) n.append(chips);
    return { domNodes: [n] };
  },
  eventClass: (info) =>
    [
      "calendar-event",
      info.event.id === state.selection ? "is-selected" : "",
      isPlanned(byKey.get(info.event.id) || {}) ? "is-planned" : "",
      planItem(byKey.get(info.event.id) || {})
        ? "plan-" + planItem(byKey.get(info.event.id)).source
        : "",
    ].join(" "),
  eventDidMount: (info) => {
    const r = byKey.get(info.event.id);
    if (!r) return;
    info.el.style.setProperty("--venue-color", r.venue?.color || "#667580");
    info.el.setAttribute(
      "aria-label",
      `${r.session.code} ${r.session.title}，${timeText(r)}，${r.venue?.name || r.session.venue || "會場未定位"}${isPlanned(r) ? "，" + planLabel(planItem(r)) : ""}`,
    );
    info.el.dataset.record = r.key;
    info.el.title = `${r.session.title}\n${timeText(r)}\n${r.session.location || ""}`;
  },
  moreLinkContent: (info) => ({
    domNodes: [el("span", "more-label", `＋${info.num} 場`)],
  }),
  moreLinkClick: (info) => {
    const ids = new Set(info.allSegs.map((segment) => segment.event.id));
    stack.compare(
      visible().filter((r) => ids.has(r.key)),
      `未展開議程 · ${ids.size} 場`,
      info.jsEvent.target.closest('[role="button"]'),
    );
    // FullCalendar 7.1.3 opens its default popover on any falsy result.
    // A truthy non-string suppresses it without navigating. Kept version-pinned;
    // verified in-browser so only our comparison dialog is opened.
    return true;
  },
});
calendar.render();
// All calendar date/view moves go through this, so it always shows state.day (see renderCalendar).
const calendarSync = createCalendarSync(calendar, state.view, state.day);
const stack = createStackCalendar({
  container: $("stack-calendar"),
  onSelect: select,
});
const filterControls = createFilterControls({
  container: $("facet-controls"),
  chips: $("filter-chips"),
  records: () => records,
  taxonomy: () => meta.taxonomy || [],
  filters: () => state,
  plan: () => state.plan,
  onChange: (patch) => {
    Object.assign(state, patch);
    renderCalendar();
  },
});
// Data-driven time axis: show only the hours that actually have sessions (plus a little margin),
// so the first screen is not six empty night hours. Bounds change only when the data changes.
let slotBounds = { min: "", max: "" };
function timeBounds(rows) {
  let min = 24,
    max = 0;
  for (const r of rows) {
    const s = r.session.start_local || "",
      e = r.session.end_local || "";
    const h = parseInt(s.slice(11, 13), 10);
    if (!Number.isNaN(h)) min = Math.min(min, h);
    if (e.slice(0, 10) !== s.slice(0, 10)) max = 24;
    else {
      const eh =
        parseInt(e.slice(11, 13), 10) + (e.slice(14, 16) === "00" ? 0 : 1);
      if (!Number.isNaN(eh)) max = Math.max(max, Math.min(24, eh));
    }
  }
  if (min >= max) return { min: "07:00:00", max: "22:00:00" };
  const pad = (n) => String(n).padStart(2, "0") + ":00:00";
  return { min: pad(Math.max(0, min)), max: pad(Math.min(24, max)) };
}
function renderCalendar(capture = true) {
  const result = visible();
  const rows = result.filter((r) => r.times);
  if (capture) captureScroll();
  calendarSync.go(state.view, state.day);
  calendar.batchRendering(() => {
    const bounds = timeBounds(rows);
    if (bounds.min !== slotBounds.min || bounds.max !== slotBounds.max) {
      slotBounds = bounds;
      calendar.setOption("slotMinTime", bounds.min);
      calendar.setOption("slotMaxTime", bounds.max);
    }
    calendar.removeAllEventSources();
    calendar.addEventSource(
      rows.map((r) => ({
        id: r.key,
        title: r.session.title,
        start: r.session.start_local,
        end: r.session.end_local,
        color: r.venue?.color || "#667580",
        textColor: "#152a35",
        extendedProps: {
          _rank: r.key === state.selection ? 0 : isPlanned(r) ? 1 : 2,
        },
      })),
    );
  });
  restoreScroll();
  stack.update({
    records: result,
    days: state.view === "day" ? [state.day] : DAYS,
    selection: state.selection,
    plan: state.plan,
    taxonomy: meta.taxonomy || [],
  });
  filterControls.update();
  $("visible-count").textContent = result.length.toLocaleString();
  $("time-status").hidden = !state.from || !state.to || state.from < state.to;
  $("context-description").textContent = state.planOnly
    ? " 場我的安排"
    : " 場符合目前條件";
  const hidden = state.plan.filter(
    (p) => !result.some((r) => r.placement === p.placement),
  );
  $("plan-count").textContent = state.plan.length;
  $("selection-status").textContent = hidden.length
    ? ` · ${hidden.length} 場安排未顯示`
    : "";
  $("empty").hidden = !catalogReady || rows.length > 0;
  const unknown = filtered().filter(
    (r) => !r.times || !DAYS.some((day) => inDay(r, day)),
  );
  $("unplaced").hidden = unknown.length === 0;
  $("unplaced-title").textContent =
    `${unknown.length} 場未排入這五天（日程未定或在範圍外）`;
  $("unplaced-list").replaceChildren(
    ...unknown.map((r) =>
      button(
        `${r.session.code} · ${r.session.title}`,
        () => select(r.key),
        "unplaced-item",
      ),
    ),
  );
  const counts = Object.fromEntries(
    VENUES.map((v) => [
      v.id,
      result.filter((r) => r.venue?.id === v.id).length,
    ]),
  );
  scene?.setVisibleVenueCounts(counts);
  const sel = selectedRecord();
  if (sel && !result.some((r) => r.key === sel.key))
    $("selection-status").textContent += " · 已選議程在目前條件外";
  renderPlanMissing();
  renderMine();
  writeURL();
}
const SOURCE_TEXT = {
  reserved: "✓ 已預約",
  favorite: "★ 官方收藏",
  local: "● 本機挑選",
};
function mineItem(p) {
  const r = byKey.get(p.key);
  const li = el("li");
  const b = el(
    "button",
    `mine-item plan-${p.source}${r && r.key === state.selection ? " is-selected" : ""}`,
  );
  b.type = "button";
  b.style.setProperty("--venue-color", r?.venue?.color || "#667580");
  b.append(
    el("span", "mine-time", `${localClock(p.start)}–${localClock(p.end)}`),
    el("span", "mine-source", SOURCE_TEXT[p.source] || SOURCE_TEXT.local),
  );
  const main = el("span", "mine-main");
  main.append(
    el("strong", "", `${p.code} · ${p.title}`),
    el(
      "span",
      "",
      [r?.venue?.name || r?.session.venue, p.location].filter(Boolean).join(" · ") ||
        "地點尚未公布",
    ),
  );
  if (seatText(r?.session.seat_availability))
    main.append(el("span", "mine-seats", seatText(r.session.seat_availability)));
  b.append(main);
  b.setAttribute("aria-label", `${planLabel(p)}：${p.code} ${p.title}，${localClock(p.start)}–${localClock(p.end)}`);
  if (r) b.addEventListener("click", () => select(r.key));
  else b.disabled = true;
  li.append(b);
  return li;
}
function renderMine() {
  if (state.tab !== "mine") return;
  const counts = dayCounts(state.plan);
  for (const b of $("mine-dates").children) {
    b.textContent = `${dayLabel(b.dataset.day)}${counts[b.dataset.day] ? ` · ${counts[b.dataset.day]}` : ""}`;
    b.setAttribute("aria-pressed", String(state.day === b.dataset.day));
  }
  const list = $("mine-agenda");
  if (planUnavailable) {
    $("mine-summary").textContent = planError || "正在讀取你的行程…";
    list.replaceChildren();
    return;
  }
  const rows = dayAgenda(state.plan, state.day);
  const sessions = rows.flatMap((row) => (row.kind === "gap" ? row.items : [row.item]));
  const n = (source) => sessions.filter((p) => p.source === source).length;
  const gaps = rows.filter((row) => row.kind === "gap").length;
  $("mine-summary").textContent = sessions.length
    ? [
        `${n("reserved")} 場已預約`,
        n("favorite") ? `${n("favorite")} 場官方收藏` : "",
        n("local") ? `${n("local")} 場本機挑選` : "",
        gaps ? `${gaps} 段空檔` : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  list.replaceChildren(
    ...rows.map((row) => {
      if (row.kind === "session") return mineItem(row.item);
      const li = el("li", "mine-gap");
      li.style.minHeight = `${Math.min(180, Math.max(44, row.minutes * 0.6))}px`;
      li.append(
        el("b", "", row.label),
        el("span", "", `${localClock(row.start)}–${localClock(row.end)} · 已預約場次之間的空檔`),
      );
      if (row.items.length) {
        const inner = el("ol", "mine-agenda");
        inner.append(...row.items.map(mineItem));
        li.append(inner);
      }
      return li;
    }),
  );
  if (!rows.length) {
    const li = el("li", "mine-empty");
    li.append(
      el("p", "", "這一天還沒有已預約、收藏或本機挑選的議程。"),
      button("到 Explore 找這天的議程", () => {
        setTab("explore", true);
        changeView("day", state.day);
      }),
    );
    list.replaceChildren(li);
  }
}
function setTab(tab, byUser = false) {
  if (byUser) homeChoice.choose(tab);
  if (state.tab === tab) return;
  captureScroll();
  state.tab = tab;
  if (tab === "mine" && state.panel === "map" && !state.selection) state.panel = "none";
  layout();
  renderCalendar(false);
}
function layout() {
  const tab = state.tab;
  $("workspace").dataset.tab = tab || "pending";
  $("mine").hidden = tab === "explore";
  $("calendar-pane").hidden = tab !== "explore";
  $("explore-controls").hidden = tab !== "explore";
  $("context-row").hidden = tab !== "explore";
  for (const [id, name] of [
    ["tab-mine", "mine"],
    ["tab-explore", "explore"],
  ]) {
    $(id).setAttribute("aria-selected", String(tab === name));
    $(id).setAttribute("aria-pressed", String(tab === name));
    $(id).tabIndex = tab === name ? 0 : -1;
  }
  $("workspace").dataset.view = state.view;
  $("workspace").dataset.layout = state.layout;
  $("calendar").hidden = state.layout === "stack";
  $("stack-calendar").hidden = state.layout !== "stack";
  for (const mode of ["stack", "overlap", "columns"])
    $("layout-" + mode).setAttribute(
      "aria-pressed",
      String(state.layout === mode),
    );
  $("layout-description").textContent =
    state.layout === "stack"
      ? "開始時段分組 · 卡疊高度不代表長度"
      : state.layout === "overlap"
        ? "依實際起訖時間重疊 · ＋N 展開全部"
        : "依實際起訖時間並排 · ＋N 展開全部";
  $("workspace").dataset.panel = state.panel;
  $("side-pane").hidden = state.panel === "none";
  $("reader-panel").hidden = state.panel !== "abstract";
  $("map-panel").hidden = state.panel !== "map";
  $("abstract-tab").setAttribute(
    "aria-selected",
    String(state.panel === "abstract"),
  );
  $("map-tab").setAttribute("aria-selected", String(state.panel === "map"));
  $("abstract-tab").tabIndex = state.panel === "abstract" ? 0 : -1;
  $("map-tab").tabIndex = state.panel === "map" ? 0 : -1;
  $("week-view").setAttribute("aria-pressed", String(state.view === "week"));
  $("day-view").setAttribute("aria-pressed", String(state.view === "day"));
  $("map-toggle").setAttribute("aria-pressed", String(state.panel === "map"));
  $("plan-view").setAttribute("aria-pressed", String(state.planOnly));
  for (const b of $("dates").children)
    b.setAttribute("aria-pressed", String(state.day === b.dataset.day));
  $("map-scope").textContent =
    state.view === "week"
      ? "本週可見議程合計，非同時"
      : `${dayLabel(state.day)} · 可見議程合計`;
  requestAnimationFrame(() => {
    calendar.render();
    scene?.resize();
    restoreScroll();
  });
}
function setPanel(panel) {
  captureScroll();
  state.panel = panel;
  layout();
  if (panel === "map") ensureScene();
}
function changeView(view, day = state.day) {
  if (!DAYS.includes(day)) return;
  captureScroll();
  const oldView = state.view;
  state.view = view;
  state.day = day;
  if (oldView !== view) {
    if (view === "day") dayScroll = weekScroll;
    else weekScroll = dayScroll;
  }
  calendarSync.go(view, day);
  if (view === "day" && state.panel === "none" && state.tab === "explore")
    state.panel = "map";
  layout();
  if (state.panel === "map") ensureScene();
  renderCalendar(false);
}
function select(key) {
  const r = byKey.get(key);
  if (!r) return;
  state.selection = key;
  state.spotlight = r.venue?.id || null;
  const day = dayForSelection(r, state.day, state.view);
  if (day !== state.day) {
    const needsNavigation = state.view === "day";
    state.day = day;
    if (needsNavigation) calendarSync.go(state.view, state.day);
  }
  setPanel("abstract");
  renderReader(r);
  scene?.setSelection(r.venue?.id || null, { focus: !!r.venue });
  renderCalendar();
  const heading = $("reader").querySelector("h2");
  heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}
async function renderReader(r) {
  const token = ++readerVersion;
  $("reader-panel").scrollTop = 0;
  const root = $("reader");
  root.replaceChildren();
  root.append(
    el("p", "eyebrow", `${r.session.code} / ${r.session.type || "形式未公布"}`),
    el("h2", "detail-title", r.session.title),
  );
  const place = el("div", "detail-meta");
  place.append(
    el("p", "detail-time", timeText(r)),
    el("p", "detail-location", r.session.location || "地點尚未公布"),
    el("p", "detail-level", r.levels.join(" · ") || "等級尚未公布"),
  );
  if (seatText(r.session.seat_availability))
    place.append(el("p", "detail-seats", seatText(r.session.seat_availability)));
  root.append(place);
  if (r.levels.length > 1)
    root.append(
      el(
        "p",
        "data-note",
        "來源等級欄位與標籤不同；兩者均保留，篩選包含兩者。",
      ),
    );
  const actions = el("div", "detail-actions");
  const planButton = button(planButtonText(r), () => togglePlan(r), "primary");
  planButton.dataset.planToggle = "";
  planButton.disabled = planToggleDisabled(r);
  actions.append(
    planButton,
    button(
      "在地圖看方位",
      () => {
        setPanel("map");
        spotlight(r.venue?.id || null, true);
      },
      "secondary",
    ),
  );
  const planNote = el("p", "local-note", planNoteText(r));
  planNote.dataset.planNote = "";
  root.append(actions, planNote);
  const translateButton = button(
    "翻譯 / Translate",
    requestTranslation,
    "secondary",
  );
  actions.append(translateButton);
  const abstract = el(
    "div",
    "abstract-text",
    r.session.abstract || "目前來源未提供摘要。",
  );
  const translated = el("section", "session-translation");
  translated.hidden = true;
  translated.setAttribute("aria-label", "Session translation");
  const transNote = el("p", "translation-note", "按需翻譯，原文保留供核對。");
  transNote.setAttribute("role", "status");
  root.append(abstract, transNote, translated);
  async function requestTranslation() {
    translateButton.disabled = true;
    transNote.textContent = "翻譯中… / Translating…";
    translated.setAttribute("aria-busy", "true");
    try {
      const profileResponse = await fetch("/api/profile");
      if (!profileResponse.ok) throw new Error("profile_unavailable");
      const profile = await profileResponse.json();
      const lang = profile.fields?.language || "zh-Hant";
      const response = await fetch(
        `/api/translate/${encodeURIComponent(r.session.session_id)}?lang=${encodeURIComponent(lang)}`,
      );
      const translation = await response.json();
      if (!response.ok)
        throw new Error(translation.error || "translation_unavailable");
      if (token !== readerVersion) return;
      translated.lang = translation.lang;
      translated.replaceChildren(
        el("h3", "detail-title", translation.title),
        el("div", "abstract-text", translation.abstract),
      );
      translated.hidden = false;
      transNote.textContent =
        translation.source === "official"
          ? `官方翻譯 / Official translation · ${translation.lang}`
          : `非官方翻譯 / unofficial translation (Nova) · ${translation.lang}${translation.cached ? " · 快取 / cached" : ""}`;
    } catch (error) {
      if (token === readerVersion)
        transNote.textContent =
          serviceErrorText(error.message) ||
          "翻譯暫時無法使用，請重試。 / Translation unavailable; please retry.";
    } finally {
      translateButton.disabled = false;
      translated.setAttribute("aria-busy", "false");
    }
  }
  for (const [label, items, kind] of [
    ["官方目錄標籤", r.officialFacets.map((f) => f.label), "official"],
    [
      "系統主題分類",
      r.systemTopics.map(
        (id) => meta.taxonomy?.find((t) => t.id === id)?.label || id,
      ),
      "system",
    ],
    ["公開文字提及公司", r.companies, "company"],
  ]) {
    root.append(el("h3", "section-label", label));
    const group = el("div", "tags tag-group-" + kind);
    for (const item of items) group.append(el("span", "tag", item));
    if (!items.length)
      group.append(el("span", "data-note", "目前沒有此類標籤。"));
    root.append(group);
  }
  const evidence = el("details", "classification-evidence");
  evidence.append(el("summary", "", "分類依據"));
  for (const reason of r.session.classification_reasons || [])
    evidence.append(el("p", "data-note", `${reason.label}：${reason.reason}`));
  for (const match of r.session.derived_company_matches || [])
    evidence.append(
      el(
        "p",
        "data-note",
        `${match.company} · ${match.field}：「${match.excerpt}」`,
      ),
    );
  evidence.append(
    el(
      "p",
      "data-note",
      "系統分類來自公開文字規則；公司名稱提及不代表主辦、贊助、講者任職或確定出席。",
    ),
  );
  root.append(evidence);
  if (r.session.speakers?.length) {
    root.append(
      el("h3", "section-label", "講者"),
      el("p", "speakers", r.session.speakers.join(" · ")),
    );
  }
  root.append(
    el(
      "p",
      "source-note",
      `來源：${r.session.source || "既有公開目錄"} · ${observationLabel(r.session.observed_at)}。${sourceTimingNote(r.session.source)}`,
    ),
  );
}
async function changePlan(item, action) {
  if (planUnavailable) {
    notify("「我的安排」尚未讀取完成，暫不修改。");
    return;
  }
  try {
    await planStore.update(item, action);
    await refreshPlan();
  } catch (error) {
    notify(error.message || "這次安排未保存；目前安排保持原樣。");
  }
}
function togglePlan(r) {
  if (planItem(r)?.source === "reserved") return cancelOfficial(r);
  return changePlan(makePlanItem(r), isPlanned(r) ? "remove" : "add");
}
// Official cancel: confirm naming the session → CancelReservation → GetSchedule read-back → re-read /api/plan.
async function cancelOfficial(r) {
  const p = planItem(r);
  if (!confirm(cancelConfirmText(p, timeText(r)))) return;
  const b = $("reader").querySelector("[data-plan-toggle]");
  if (b) b.disabled = true;
  notify("正在向 AWS Events 取消預約…");
  try {
    const item = await cancelReservation(r.session.session_id);
    const byId = new Map(records.map((x) => [x.session.session_id, x.session.code]));
    notify(cancelResultText(item, (id) => byId.get(id) || id));
  } catch (error) {
    notify("未取消：" + (error.message || "請稍後再試。"));
  }
  window.dispatchEvent(new Event(PLAN_CHANGED)); // re-reads /api/plan here and on Copilot's cards
}
function refreshPlanButton() {
  const r = selectedRecord();
  const b = $("reader").querySelector("[data-plan-toggle]");
  if (r && b) {
    b.textContent = planButtonText(r);
    b.disabled = planToggleDisabled(r);
  }
  const note = $("reader").querySelector("[data-plan-note]");
  if (r && note) note.textContent = planNoteText(r);
}
// Re-reads /api/plan on Copilot's update event and when the tab is shown again (see watchPlan).
// Signed in → My re:Invent on the attendee's day; signed out → Explore. Either proof of sign-in
// (/api/auth/status or /api/plan's official.status == "live") can decide or change the tab.
const homeChoice = createHomeChoice({
  requested: requestedTab,
  onChange: applyHome,
});
function applyHome({ tab, previous, signedIn }) {
  $("home-tabs").hidden = !signedIn;
  if (tab === previous) return;
  if (tab === "mine" && !dayFromURL) state.day = homeDay();
  if (
    previous === null &&
    tab === "explore" &&
    state.view === "day" &&
    state.panel === "none" &&
    !state.selection
  )
    state.panel = "map";
  setTab(tab);
  if (state.panel === "map") ensureScene();
}
const refreshPlan = watchPlan({
  store: planStore,
  onPlan(loaded, official) {
    const items = canonicalPlan(loaded);
    const changed =
      planUnavailable || JSON.stringify(items) !== JSON.stringify(state.plan);
    state.plan = items;
    planUnavailable = false;
    const officialError =
      official?.status === "error"
        ? "官方行程暫時無法讀取；「我的安排」目前只列出本機挑選。"
        : "";
    if (planError && $("notice").textContent === planError) notify("");
    planError = officialError;
    if (officialError) notify(officialError);
    if (changed) renderCalendar();
    refreshPlanButton();
    homeChoice.plan(official?.status);
  },
  onError(error) {
    planUnavailable = true;
    planError = error.message || "暫時無法讀取「我的安排」；請稍後再試。";
    notify(planError);
    refreshPlanButton();
  },
});
function spotlight(id, focus = false) {
  state.spotlight = id;
  const v = VENUES.find((v) => v.id === id);
  const n = $("venue-spotlight");
  n.replaceChildren();
  if (!v) {
    n.append(
      el("strong", "", selectedRecord()?.session.venue || "會場尚未定位"),
      el("p", "", "保留官方地點文字；未把議程放到猜測的位置。"),
    );
    scene?.setSelection(null);
    return;
  }
  n.append(
    el("strong", "", v.name),
    el(
      "p",
      "",
      "已核對 OSM 命名建物；會議區、房間與入口未定位。未知高度維持平面。",
    ),
    button(
      "篩選此會場",
      () => {
        state.venues = [id];
        renderCalendar();
      },
      "venue-filter-button",
    ),
  );
  scene?.setSelection(id, { focus });
}
function ensureScene() {
  if (!scene) {
    scene = createScene({
      container: $("map"),
      onVenueSelect: (id) => spotlight(id),
      onStatus: (message) => {
        $("map-status").textContent = message;
      },
    });
    scene.ready.then(() => {
      const counts = Object.fromEntries(
        VENUES.map((v) => [
          v.id,
          visible().filter((r) => r.venue?.id === v.id).length,
        ]),
      );
      scene.setVisibleVenueCounts(counts);
      scene.setSelection(
        state.spotlight || selectedRecord()?.venue?.id || null,
      );
    });
  }
  scene.resize();
  if (state.spotlight) spotlight(state.spotlight);
}
for (const day of DAYS) {
  const b = button(dayLabel(day), () => changeView("day", day));
  b.dataset.day = day;
  $("dates").append(b);
  const m = button(dayLabel(day), () => {
    state.day = day;
    renderCalendar(false);
  });
  m.dataset.day = day;
  $("mine-dates").append(m);
}
$("tab-mine").onclick = () => setTab("mine", true);
$("tab-explore").onclick = () => setTab("explore", true);
for (const tab of [$("tab-mine"), $("tab-explore")])
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const next = state.tab === "mine" ? "explore" : "mine";
    setTab(next, true);
    $("tab-" + next).focus();
  });
$("week-view").onclick = () => changeView("week");
$("day-view").onclick = () => changeView("day");
$("map-toggle").onclick = () =>
  setPanel(state.panel === "map" ? "none" : "map");
$("close-panel").onclick = () => setPanel("none");
$("abstract-tab").onclick = () => setPanel("abstract");
$("map-tab").onclick = () => setPanel("map");
for (const tab of [$("abstract-tab"), $("map-tab")]) {
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? "abstract"
        : event.key === "End"
          ? "map"
          : state.panel === "map"
            ? "abstract"
            : "map";
    setPanel(next);
    $(next === "map" ? "map-tab" : "abstract-tab").focus();
  });
}
$("top").onclick = () => {
  scene?.setPitch(0);
  $("top").setAttribute("aria-pressed", "true");
  $("oblique").setAttribute("aria-pressed", "false");
};
$("oblique").onclick = () => {
  scene?.setPitch(50);
  $("top").setAttribute("aria-pressed", "false");
  $("oblique").setAttribute("aria-pressed", "true");
};
$("north").onclick = () => scene?.reset();
$("plan-view").onclick = () => {
  state.planOnly = !state.planOnly;
  layout();
  renderCalendar();
};
for (const mode of ["stack", "overlap", "columns"])
  $("layout-" + mode).onclick = () => {
    captureScroll();
    stack.closeComparison();
    state.layout = mode;
    calendar.setOption("slotEventOverlap", mode === "overlap");
    layout();
    renderCalendar(false);
  };
function renderPlanMissing() {
  if (!state.planOnly || !catalogReady || meta.stale) return;
  const missing = state.plan.filter(
    (p) => !records.some((r) => r.placement === p.placement),
  );
  if (!missing.length) return;
  $("unplaced").hidden = false;
  $("unplaced-title").textContent = `${missing.length} 場已安排時段待核對`;
  $("unplaced-list").replaceChildren(
    ...missing.map((p) => {
      const n = el("div", "missing-plan");
      n.append(
        el("strong", "", `${p.code} · ${p.title}`),
        el("p", "", `${p.start} — ${p.end} · ${p.location}`),
        el(
          "p",
          "",
          "這筆安排尚未對照目前的官方資料來源；不代表已取消或從官方目錄移除。",
        ),
        p.source === "local"
          ? button("移除這筆本機安排", () => changePlan(p, "remove"))
          : el("p", "", `${planLabel(p)}；請在 AWS Events 變更。`),
      );
      return n;
    }),
  );
}
function syncControls() {
  for (const k of ["query", "from", "to"]) $(k).value = state[k];
}
let debounce;
for (const k of ["query", "from", "to"])
  $(k).addEventListener(k === "query" ? "input" : "change", () => {
    state[k] = $(k).value;
    clearTimeout(debounce);
    debounce = setTimeout(
      () => {
        renderCalendar();
      },
      k === "query" ? 150 : 0,
    );
  });
$("filters").onsubmit = (e) => e.preventDefault();
$("clear").onclick = () => {
  Object.assign(state, normaliseFilters());
  syncControls();
  layout();
  renderCalendar();
};
let catalogRequest = null;
let catalogRetryAt = 0;
let catalogAttempts = 0;
function load() {
  if (catalogRequest) return catalogRequest;
  if (Date.now() < catalogRetryAt) {
    notify("官方服務要求稍後重試；請等待後再重新讀取議程。");
    return Promise.resolve();
  }
  catalogRequest = loadCatalog().finally(() => {
    catalogRequest = null;
  });
  return catalogRequest;
}
async function loadCatalog() {
  catalogAttempts += 1;
  const control = $("reload");
  control.disabled = true;
  try {
    const [response, trans] = await Promise.all([
      fetch("/api/catalog"),
      fetch("/translations.json")
        .then((r) => (r.ok ? r.json() : []))
        .catch(() => []),
    ]);
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      if (response.status === 429) {
        const header = response.headers.get("Retry-After");
        const seconds = Number(header);
        const delay =
          header && Number.isFinite(seconds)
            ? seconds * 1000
            : Date.parse(header) - Date.now();
        catalogRetryAt =
          Date.now() +
          (Number.isFinite(delay) && delay > 0 ? Math.max(delay, 1000) : 60000);
      }
      const error = Error();
      error.code =
        failure.error || (response.status === 429 ? "rate_limited" : null);
      throw error;
    }
    const d = validateCatalog(await response.json());
    meta = d.meta;
    catalogReady = true;
    records = enrichRecords(prepare(d.sessions, VENUES), meta.taxonomy || []);
    byKey = new Map(records.map((r) => [r.key, r]));
    translations = Array.isArray(trans) ? trans : [];
    syncControls();
    $("freshness").textContent =
      `${d.sessions.length.toLocaleString()} 場 · ${observationLabel(meta.catalog_observed_at)}${meta.stale ? " · 離線快取" : ""}`;
    if (meta.stale) notify("目前顯示上次成功的官方議程，來源暫時無法更新。");
    else if (!planError) notify("");
    renderCalendar();
    if (selectedRecord()) renderReader(selectedRecord());
    renderPlanMissing();
    void refreshPlan();
  } catch (error) {
    if (["sign_in_required", "not_registered"].includes(error.code))
      officialConnection.requireSignIn(error.code);
    notify(catalogFailureMessage(error.code, records.length > 0));
    $("freshness").textContent = records.length
      ? "保留上次目錄"
      : error.code === "sign_in_required"
        ? "等待官方登入"
        : "議程載入失敗";
  } finally {
    control.disabled = false;
  }
}
const officialConnection = createOfficialConnection({
  onChange(auth) {
    const copy = connectionCopy(auth);
    $("connection-status").textContent = copy.title;
    $("official-sign-in").textContent = auth.starting
      ? "準備登入…"
      : copy.button;
    $("official-sign-in").disabled = auth.starting || copy.disabled;
    $("official-sign-in").closest("section").dataset.connected = String(
      auth.connected,
    );
    if (!auth.connected && !records.length)
      $("freshness").textContent = auth.checking
        ? "確認官方連線…"
        : "等待官方登入";
    if (auth.checked && !auth.checking) homeChoice.auth(auth.connected);
  },
  onConnected: load,
});
// Copilot's 60 s status poll keeps the one sign-in button current: re-enabled once signed out or
// expired, "再次登入" shortly before expiry. A sign-out also re-reads the plan (official status).
addEventListener(AUTH_STATUS_EVENT, (event) => {
  officialConnection.applyStatus(event.detail || {});
  if (event.detail?.signed_in === false) void refreshPlan();
});
$("official-sign-in").onclick = async () => {
  const authorizationUrl = await officialConnection.start();
  if (!authorizationUrl) return;
  try {
    sessionStorage.setItem(SIGN_IN_RETURN_KEY, location.hash);
  } catch {}
  location.assign(authorizationUrl);
};
$("reload").onclick = async () => {
  const beforeRefresh = catalogAttempts;
  const auth = await officialConnection.refresh();
  if (auth.connected && beforeRefresh === catalogAttempts) await load();
};
layout();
if (state.panel === "map") ensureScene();
await Promise.all([officialConnection.refresh(), refreshPlan()]);
addEventListener("pagehide", (event) => {
  // A history-cached page will resume these same objects on Back.
  if (event.persisted) return;
  officialConnection.stop();
  scene?.destroy();
  calendar.destroy();
  stack.destroy();
  filterControls.destroy();
});
addEventListener("pageshow", (event) => {
  if (event.persisted) {
    void officialConnection.refresh();
    scene?.resize();
  }
});
