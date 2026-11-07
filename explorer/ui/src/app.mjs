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
import { createPlanStore } from "./plan-store.mjs";
import {
  createOfficialConnection,
  connectionCopy,
  catalogFailureMessage,
  sourceTimingNote,
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
// This stores only the current calendar view, never an authorization URL or token.
if (new URLSearchParams(location.search).get("signin") === "complete") {
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
let planUnavailable = true,
  planRefresh = 0,
  planError = "";
const notify = (message) => {
  $("notice").textContent = message;
  $("notice").hidden = !message;
};
try {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of ["view", "day", "layout", "selection"])
    if (p.has(k)) state[k] = p.get(k);
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
else if (state.view === "day") state.panel = "map";
function writeURL() {
  const p = new URLSearchParams({
    view: state.view,
    day: state.day,
    layout: state.layout,
    filters: "1",
  });
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
  const p = planItem(r);
  if (!p) return "＋ 加入我的安排";
  if (p.source === "reserved") return "✓ 官方已預約 · 請在 AWS Events 變更";
  if (p.source === "favorite") return "★ 官方收藏 · 請在 AWS Events 變更";
  return "● 已在我的安排 · 移除";
}
function planToggleDisabled(r) {
  return planUnavailable || ["reserved", "favorite"].includes(planItem(r)?.source);
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
  writeURL();
}
function layout() {
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
  calendar.changeView(
    view === "week" ? "fiveDays" : "timeGridDay",
    view === "week" ? DAYS[0] : day,
  );
  if (view === "day" && state.panel === "none") state.panel = "map";
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
    if (needsNavigation) calendar.gotoDate(state.day);
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
  root.append(
    actions,
    el("p", "local-note", "只修改本機安排，不提交 RSVP；可以保留重疊。"),
  );
  const lang = el("div", "language-tabs");
  const english = button("原文", () => showLanguage("original"));
  english.setAttribute("aria-pressed", "true");
  const chinese = button("繁中翻譯", () => showLanguage("zh"));
  chinese.disabled = true;
  lang.append(english, chinese);
  root.append(lang);
  const abstract = el(
    "div",
    "abstract-text",
    r.session.abstract || "目前來源未提供摘要。",
  );
  root.append(abstract);
  const transNote = el(
    "p",
    "translation-note",
    "保留來源完整文字。繁中譯文僅在已有且原文指紋相符時提供。",
  );
  root.append(transNote);
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
  let translation = null;
  function showLanguage(mode) {
    english.setAttribute("aria-pressed", String(mode === "original"));
    chinese.setAttribute("aria-pressed", String(mode === "zh"));
    abstract.textContent =
      mode === "zh" ? translation.abstract_translation : r.session.abstract;
    transNote.textContent =
      mode === "zh"
        ? "AI 繁中完整譯文 · 非官方翻譯；可切回原文核對。"
        : "保留來源完整文字。";
  }
  try {
    const hash = await abstractHash(r.session.abstract || "");
    if (token !== readerVersion) return;
    translation = translations.find(
      (t) =>
        t.session_id === r.session.session_id &&
        t.source_abstract_sha256 === hash,
    );
    if (translation) {
      chinese.disabled = false;
      transNote.textContent = "此篇已有繁中完整譯文，可切換閱讀；非官方翻譯。";
    } else
      transNote.textContent = "此篇尚無對應的繁中完整譯文，先顯示來源原文。";
  } catch {
    if (token === readerVersion)
      transNote.textContent = "無法核對譯文版本，保留原文。";
  }
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
  return changePlan(makePlanItem(r), isPlanned(r) ? "remove" : "add");
}
function refreshPlanButton() {
  const r = selectedRecord();
  const b = $("reader").querySelector("[data-plan-toggle]");
  if (r && b) {
    b.textContent = planButtonText(r);
    b.disabled = planToggleDisabled(r);
  }
}
async function refreshPlan() {
  const request = ++planRefresh;
  try {
    const items = canonicalPlan(await planStore.load());
    if (request !== planRefresh) return;
    const changed =
      planUnavailable || JSON.stringify(items) !== JSON.stringify(state.plan);
    state.plan = items;
    planUnavailable = false;
    const officialError =
      planStore.official?.status === "error"
        ? "官方行程暫時無法讀取；「我的安排」目前只列出本機挑選。"
        : "";
    if (planError && $("notice").textContent === planError) notify("");
    planError = officialError;
    if (officialError) notify(officialError);
    if (changed) renderCalendar();
    refreshPlanButton();
  } catch (error) {
    if (request !== planRefresh) return;
    planUnavailable = true;
    planError = error.message || "暫時無法讀取「我的安排」；請稍後再試。";
    notify(planError);
    refreshPlanButton();
  }
}
// Nova Copilot (same page) dispatches this after it changes the plan or the official schedule.
addEventListener("atlas:plan-changed", () => refreshPlan());
addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshPlan();
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
}
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
  },
  onConnected: load,
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
