// Official reservation lifecycle on Atlas cards: button state, seat words, cancel call and its result in plain words.

const SEATS = {
  available: "尚有座位",
  limited: "座位有限",
  veryLimited: "所剩極少",
  unavailable: "已滿",
  walkUp: "現場排隊",
};
export const seatText = (value) => SEATS[value] || "";

// Per-item codes from ReserveSessions / AssociateFavorites, plus CancelReservation's 409/401/429/5xx outcomes.
const FAILURES = {
  sessionNotReservable: "這場議程不開放預約。",
  scheduleConflict: "與你行程中已有的議程時間重疊。",
  alreadyScheduled: "已經在你的行程中。",
  sessionFull: "這場議程已滿。",
  insufficientAccess: "你的報名身分無法參加這場議程。",
  timePassed: "這場議程已開始或已結束。",
  alreadyFavorited: "已經在你的收藏中。",
  notFavorited: "不在你的收藏中。",
  other: "AWS Events 拒絕了，未說明原因。",
  operationClosed: "AWS Events 目前暫停這項操作，請稍後再試。",
  not_reported: "AWS Events 沒有回報結果，請到 AWS Events 確認行程。",
  official_sign_in_required: "登入已過期，請重新登入 AWS Events。",
  official_rate_limited: "AWS Events 目前忙碌，請稍候一分鐘再試。",
  catalog_unavailable: "AWS Events 沒有回應，重試前請先確認行程。",
};
export function failureText(item, codeOf = (id) => id) {
  const also = item.conflicts_with?.length
    ? `（${item.conflicts_with.map(codeOf).join("、")}）`
    : "";
  const text = FAILURES[item.code];
  return text
    ? text.replace(/。$/, also + "。")
    : `AWS Events 拒絕了（代碼：${item.code || "none"}${also}），請到 AWS Events 查看。`;
}

export function planButtonText(p) {
  if (!p) return "＋ 加入我的安排";
  if (p.source === "reserved") return "取消官方預約";
  if (p.source === "favorite") return "★ 官方收藏 · 請在 AWS Events 變更";
  return "● 已在我的安排 · 移除";
}
export const planToggleDisabled = (p, unavailable) =>
  unavailable || p?.source === "favorite";

export const cancelConfirmText = (p, when) =>
  `取消官方預約？\n${p.code} · ${p.title}\n${when}\n座位會釋出，之後不一定能再預約到。`;

export function cancelResultText(item, codeOf) {
  if (!item.ok) return "未取消：" + failureText(item, codeOf);
  if (item.in_schedule_reserved !== false)
    return "AWS Events 已受理取消，但重新讀取的官方行程仍列為已預約；請到 AWS Events 確認。";
  return item.already_gone
    ? "✓ 這場原本就不在預約中；已在官方行程中確認。"
    : "✓ 已取消，並已在官方行程中確認（不再列為已預約）。";
}

// POST /api/rsvp/cancel for one session; returns its per-item result (throws on a request-level error).
export async function cancelReservation(
  sessionId,
  { fetch = globalThis.fetch } = {},
) {
  const response = await fetch("/api/rsvp/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_ids: [sessionId] }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || "取消未送出；官方行程保持原樣。");
  return (data.results || [])[0] || { ok: false, code: "not_reported" };
}
