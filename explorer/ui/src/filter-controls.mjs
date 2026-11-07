import {
  DISCOVERY_DIMENSIONS,
  facetChoices,
  normaliseFilters,
} from "./discovery.mjs";
import { FACET_DEFINITIONS } from "./session-facets.mjs";
import { normalize } from "./model.mjs";

const LABELS = Object.freeze({
  topics: "系統主題",
  tags: "官方標籤",
  companies: "公司文字關聯",
  types: "活動形式",
  levels: "難度",
  venues: "會場",
  dates: "日期",
});
const NOTES = Object.freeze({
  topics: "系統依公開標題、摘要與官方標籤歸類，可在議程詳情查看依據。",
  tags: "保留官方公開目錄的原始標籤；下列分類是本工具的整理。",
  companies: "只代表公開文字明確提及公司，不代表贊助、講者任職或公司出席。",
  types: "保留官方形式；標題明確寫出 GameDay 等活動時，另標示「標題推定」。",
  levels: "同時保留來源等級欄位與原始標籤中的難度。",
  venues: "依已核對的公開會場名稱整理，未定位的場次仍可選取。",
  dates: "以實際起訖判斷；跨午夜場次可同時屬於兩天。",
});
const categoryLabels = new Map(
  FACET_DEFINITIONS.map((entry) => [entry.id, entry.label]),
);
// Calendar date tabs own date navigation; the data model still supports date facets.
const UI_DIMENSIONS = DISCOVERY_DIMENSIONS.filter(
  (dimension) => dimension !== "dates",
);
const bounded = (value, limit = 512) => String(value ?? "").slice(0, limit);
let instance = 0;

/** Native, keyboard-accessible multi-select controls. No DOM access at import time. */
export function createFilterControls({
  container,
  chips,
  records,
  taxonomy,
  filters,
  plan,
  onChange,
}) {
  if (!container || !chips || typeof onChange !== "function")
    throw new TypeError("篩選控制項缺少容器或更新函式。");
  const document = container.ownerDocument;
  const prefix = `discovery-filters-${++instance}`;
  const groups = new Map();
  const chipNodes = new Map();
  const listeners = [];
  let destroyed = false;
  const node = (tag, className = "", text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = bounded(text, 1000);
    return element;
  };
  const listen = (target, type, listener, options) => {
    target.addEventListener(type, listener, options);
    listeners.push(() => target.removeEventListener(type, listener, options));
  };
  const readState = () => normaliseFilters(filters?.() || {});
  const close = (group, focus = false) => {
    group.details.open = false;
    if (focus) group.summary.focus();
  };
  const setSelection = (dimension, values) => {
    if (destroyed) return;
    onChange({ [dimension]: values });
    update();
  };
  function searchGroup(group) {
    const tokens = normalize(group.search.value).split(" ").filter(Boolean);
    let visible = 0;
    for (const option of group.options.values()) {
      const text = normalize(`${option.label.textContent} ${option.category}`);
      option.root.hidden = !tokens.every((token) => text.includes(token));
      if (!option.root.hidden) visible += 1;
    }
    for (const category of group.categories.values()) {
      category.root.hidden = ![...category.root.children].some(
        (child) => child !== category.legend && !child.hidden,
      );
    }
    group.empty.hidden = visible > 0;
    group.empty.textContent = group.options.size
      ? "找不到符合的選項，可清除搜尋文字。"
      : "目前沒有可選項目。";
  }
  function createGroup(dimension) {
    const details = node("details", "facet-group");
    details.dataset.dimension = dimension;
    const summary = node("summary", "facet-summary");
    const panel = node("div", "facet-popover");
    panel.id = `${prefix}-${dimension}-panel`;
    summary.setAttribute("aria-controls", panel.id);
    const note = node(
      "p",
      "facet-note",
      `${NOTES[dimension]} 數字是在其他篩選條件下，具有此值的議程數；不是勾選後的預估總數。`,
    );
    note.id = `${prefix}-${dimension}-note`;
    const searchLabel = node(
      "label",
      "facet-search-label",
      `搜尋${LABELS[dimension]}`,
    );
    const search = node("input", "facet-search");
    search.type = "search";
    search.maxLength = 200;
    search.placeholder = "輸入文字縮小選項";
    search.setAttribute("aria-describedby", note.id);
    searchLabel.append(search);
    const toolbar = node("div", "facet-toolbar");
    const clear = node("button", "facet-clear", "清除此組");
    clear.type = "button";
    clear.setAttribute("aria-label", `清除${LABELS[dimension]}所有選取`);
    const selected = node("span", "facet-selected-count");
    toolbar.append(selected, clear);
    const optionsRoot = node("div", "facet-options");
    const empty = node("p", "facet-empty");
    empty.hidden = true;
    panel.append(note, searchLabel, toolbar, optionsRoot, empty);
    details.append(summary, panel);
    container.append(details);
    const group = {
      dimension,
      details,
      summary,
      panel,
      search,
      clear,
      selected,
      optionsRoot,
      empty,
      options: new Map(),
      categories: new Map(),
    };
    listen(search, "input", () => searchGroup(group));
    listen(clear, "click", () => {
      setSelection(dimension, []);
      search.focus();
    });
    // Delegation avoids retaining one event handler per catalogue option.
    listen(optionsRoot, "change", (event) => {
      const input = event.target;
      if (input?.type !== "checkbox" || !input.dataset.value) return;
      const state = readState();
      const next = state[dimension].filter(
        (value) => value !== input.dataset.value,
      );
      if (input.checked) next.push(input.dataset.value);
      setSelection(dimension, next);
    });
    return group;
  }
  for (const dimension of UI_DIMENSIONS)
    groups.set(dimension, createGroup(dimension));

  listen(container, "keydown", (event) => {
    if (event.key !== "Escape") return;
    const group = [...groups.values()].find(
      (entry) => entry.details.open && entry.details.contains(event.target),
    );
    if (!group) return;
    event.preventDefault();
    event.stopPropagation();
    close(group, true);
  });
  listen(
    document,
    "pointerdown",
    (event) => {
      for (const group of groups.values())
        if (group.details.open && !group.details.contains(event.target))
          close(group);
    },
    true,
  );
  listen(chips, "click", (event) => {
    const chip = event.target.closest?.("button[data-filter-dimension]");
    if (!chip || !chips.contains(chip)) return;
    const dimension = chip.dataset.filterDimension;
    const value = chip.dataset.filterValue;
    const current = [...chips.children];
    const index = current.indexOf(chip);
    setSelection(
      dimension,
      readState()[dimension].filter((entry) => entry !== value),
    );
    const remaining = [...chips.children];
    (
      remaining[Math.min(index, remaining.length - 1)] ||
      groups.get(dimension).summary
    ).focus();
  });

  function categoryFor(group, category) {
    const key = group.dimension === "tags" ? category || "other" : "all";
    if (!group.categories.has(key)) {
      const root = node("fieldset", "facet-category");
      const legend = node(
        "legend",
        "",
        key === "all"
          ? `${LABELS[group.dimension]}選項`
          : categoryLabels.get(key) || key,
      );
      root.append(legend);
      group.optionsRoot.append(root);
      group.categories.set(key, { root, legend });
    }
    return group.categories.get(key);
  }
  function optionFor(group, choice) {
    let option = group.options.get(choice.value);
    if (!option) {
      const root = node("label", "facet-option");
      const input = node("input");
      input.type = "checkbox";
      input.value = choice.value;
      input.dataset.value = choice.value;
      const label = node("span", "facet-option-label");
      const count = node("span", "facet-option-count");
      const source = node("span", "facet-option-source");
      root.append(input, label, count, source);
      option = { root, input, label, count, source, category: "" };
      group.options.set(choice.value, option);
    }
    return option;
  }
  // Only move a node when order changed; preserving the node also preserves focus.
  function orderChildren(parent, ordered, offset = 0) {
    ordered.forEach((child, index) => {
      const current = parent.children[index + offset];
      if (current !== child) parent.insertBefore(child, current || null);
    });
  }
  function renderGroup(group, choices, state) {
    const scroll = group.optionsRoot.scrollTop;
    const focused = group.optionsRoot.contains(document.activeElement)
      ? document.activeElement
      : null;
    const selected = new Set(state[group.dimension]);
    group.summary.textContent = `${LABELS[group.dimension]}${selected.size ? ` · ${selected.size}` : " · 全部"}`;
    group.summary.setAttribute(
      "aria-label",
      `${LABELS[group.dimension]}，${selected.size ? `已選 ${selected.size} 項` : "未限制"}`,
    );
    group.selected.textContent = `已選 ${selected.size} 項 · 同組任一符合`;
    group.clear.disabled = selected.size === 0;
    const valid = new Set(choices.map((choice) => choice.value));
    for (const [value, option] of group.options) {
      if (!valid.has(value)) {
        const hadFocus = document.activeElement === option.input;
        option.root.remove();
        group.options.delete(value);
        if (hadFocus) group.search.focus();
      }
    }
    const order = new Map();
    for (const choice of choices) {
      const option = optionFor(group, choice);
      option.input.checked = selected.has(choice.value);
      // Zero-count choices stay enabled, including restored unknown selections.
      option.label.textContent = bounded(choice.label);
      const count = Number.isFinite(choice.count)
        ? Math.max(0, choice.count)
        : 0;
      option.count.textContent = String(count);
      option.count.setAttribute("aria-label", `${count} 場`);
      const provenance = Array.isArray(choice.provenance)
        ? choice.provenance
        : [];
      const official = provenance.some((item) => item.source === "official");
      option.source.textContent =
        group.dimension === "types" &&
        !official &&
        provenance.some((item) => item.source === "inferred_title")
          ? "標題推定"
          : "";
      option.source.hidden = !option.source.textContent;
      option.root.classList.toggle("is-selected", option.input.checked);
      option.root.classList.toggle("is-zero", count === 0);
      option.category = bounded(
        categoryLabels.get(choice.category) || choice.category || "",
      );
      const category = categoryFor(group, choice.category);
      if (!order.has(category)) order.set(category, []);
      order.get(category).push(option.root);
    }
    for (const [category, children] of order)
      orderChildren(category.root, children, 1);
    searchGroup(group);
    if (focused?.isConnected && document.activeElement !== focused)
      focused.focus({ preventScroll: true });
    group.optionsRoot.scrollTop = scroll;
  }
  function renderChips(state, allChoices) {
    const desired = [];
    const valid = new Set();
    for (const dimension of UI_DIMENSIONS) {
      const labels = new Map(
        allChoices.get(dimension).map((choice) => [choice.value, choice.label]),
      );
      for (const value of state[dimension]) {
        const key = JSON.stringify([dimension, value]);
        valid.add(key);
        let chip = chipNodes.get(key);
        if (!chip) {
          chip = node("button", "filter-chip");
          chip.type = "button";
          chip.dataset.filterDimension = dimension;
          chip.dataset.filterValue = value;
          chipNodes.set(key, chip);
        }
        const label = bounded(labels.get(value) || value);
        chip.textContent = `${LABELS[dimension]}：${label} ×`;
        chip.setAttribute(
          "aria-label",
          `移除${LABELS[dimension]}篩選：${label}`,
        );
        desired.push(chip);
      }
    }
    for (const [key, chip] of chipNodes)
      if (!valid.has(key)) {
        chip.remove();
        chipNodes.delete(key);
      }
    orderChildren(chips, desired);
    chips.hidden = desired.length === 0;
  }
  function update() {
    if (destroyed) return;
    const state = readState();
    const rows = records?.() || [];
    const definitions = taxonomy?.() || [];
    const planned = plan?.() || [];
    const choices = new Map();
    for (const dimension of UI_DIMENSIONS) {
      const options = facetChoices(
        rows,
        state,
        planned,
        dimension,
        definitions,
      ).sort(
        (a, b) =>
          Number(a.count === 0) - Number(b.count === 0) ||
          a.label.localeCompare(b.label) ||
          a.value.localeCompare(b.value),
      );
      choices.set(dimension, options);
      renderGroup(groups.get(dimension), options, state);
    }
    renderChips(state, choices);
  }
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    for (const remove of listeners) remove();
    for (const group of groups.values()) group.details.remove();
    for (const chip of chipNodes.values()) chip.remove();
    groups.clear();
    chipNodes.clear();
  }
  update();
  return { update, destroy };
}
