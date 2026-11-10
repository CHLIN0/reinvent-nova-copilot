import { test } from "node:test";
import assert from "node:assert/strict";
import {
  seatText,
  failureText,
  planButtonText,
  planToggleDisabled,
  cancelConfirmText,
  cancelResultText,
  cancelReservation,
} from "./src/rsvp.mjs";

const p = (source) => ({ source, code: "SYN-KEY02", title: "Keynote" });

test("a reserved session offers the official cancel; favorites stay read-only", () => {
  assert.equal(planButtonText(p("reserved")), "取消官方預約");
  assert.equal(planToggleDisabled(p("reserved"), false), false);
  assert.equal(
    planButtonText(p("favorite")),
    "★ 官方收藏 · 請在 AWS Events 變更",
  );
  assert.equal(planToggleDisabled(p("favorite"), false), true);
  assert.equal(planButtonText(p("local")), "● 已在我的安排 · 移除");
  assert.equal(planButtonText(undefined), "＋ 加入我的安排");
  assert.equal(planToggleDisabled(p("reserved"), true), true); // plan not loaded yet
});

test("seat availability in plain words, nothing when empty", () => {
  assert.deepEqual(
    ["available", "limited", "veryLimited", "unavailable", "walkUp"].map(
      seatText,
    ),
    ["尚有座位", "座位有限", "所剩極少", "已滿", "現場排隊"],
  );
  assert.equal(seatText(null), "");
  assert.equal(seatText(""), "");
});

test("the confirm names code, title and time", () => {
  const text = cancelConfirmText(p("reserved"), "12/2（三） · 08:00–10:00");
  for (const part of ["SYN-KEY02", "Keynote", "08:00–10:00"])
    assert.ok(text.includes(part));
});

test("results in plain words, with conflicting codes and unknown codes verbatim", () => {
  const codes = { a: "SYN-AI303" };
  assert.equal(
    failureText(
      { code: "scheduleConflict", conflicts_with: ["a", "b"] },
      (id) => codes[id] || id,
    ),
    "與你行程中已有的議程時間重疊（SYN-AI303、b）。",
  );
  assert.equal(failureText({ code: "sessionFull" }), "這場議程已滿。");
  assert.equal(
    failureText({ code: "brandNewCode" }),
    "AWS Events 拒絕了（代碼：brandNewCode），請到 AWS Events 查看。",
  );
  assert.equal(
    cancelResultText({ ok: true, in_schedule_reserved: false }),
    "✓ 已取消，並已在官方行程中確認（不再列為已預約）。",
  );
  assert.match(
    cancelResultText({ ok: true, in_schedule_reserved: true }),
    /仍列為已預約/,
  );
  assert.match(
    cancelResultText({
      ok: true,
      already_gone: true,
      in_schedule_reserved: false,
    }),
    /原本就不在預約中/,
  );
  assert.equal(
    cancelResultText({ ok: false, code: "operationClosed" }),
    "未取消：AWS Events 目前暫停這項操作，請稍後再試。",
  );
});

test("cancelReservation posts one session id to the click-only route", async () => {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      json: async () => ({
        results: [{ session_id: "s1", ok: true, in_schedule_reserved: false }],
      }),
    };
  };
  const item = await cancelReservation("s1", { fetch });
  assert.equal(calls[0].url, "/api/rsvp/cancel");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { session_ids: ["s1"] });
  assert.equal(item.ok, true);
  const failing = async () => ({
    ok: false,
    json: async () => ({ error: "CatalogError: Not signed in" }),
  });
  await assert.rejects(
    cancelReservation("s1", { fetch: failing }),
    /Not signed in/,
  );
});

test("cancel shows the sign-in sentence for an expired sign-in", async () => {
  const fetch = async () => ({
    ok: false,
    json: async () => ({ error: "signin_expired", message: "Your AWS Events sign-in has expired." }),
  });
  await assert.rejects(cancelReservation("s-1", { fetch }), {
    message: "登入已過期，請從頁面上方重新登入。",
  });
});
