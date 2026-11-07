// Only safe connection metadata leaves this controller. Authorization URLs are
// returned to the explicit click handler, never persisted or included in status.
// Copilot's status poll (web/copilot.js, every 60 s) announces the server's sign-in state with this
// window event, detail {signed_in, soon}; Atlas's sign-in button is the only sign-in control.
export const AUTH_STATUS_EVENT = "atlas:auth-status";

export function connectionCopy(state) {
  if (state.checking && !state.checked)
    return {
      title: "正在確認官方連線…",
      button: "登入 AWS Events",
      disabled: true,
    };
  if (state.connected && state.expiring)
    return {
      title: "AWS Events 登入即將到期；請再次登入，以免中斷官方議程與行程讀取。",
      button: "再次登入",
      disabled: false,
    };
  if (state.connected)
    return {
      title: "已完成 AWS Events 登入",
      button: "已登入",
      disabled: true,
    };
  if (state.error === "not_registered")
    return {
      title: "這個帳號尚未取得活動存取權。請確認已完成 re:Invent 註冊。",
      button: "登入 AWS Events",
      disabled: false,
    };
  if (
    state.error === "callback_unavailable" ||
    state.callback_available === false
  )
    return {
      title:
        "本機登入回呼連線埠目前不可用。確認連線埠可用後，可按「重試登入」讓服務重新嘗試；詳情請看啟動服務的 Terminal 訊息。",
      button: "重試登入",
      disabled: false,
    };
  if (state.error === "rate_limited")
    return {
      title: "官方服務目前限流，請稍後再試。",
      button: state.pending_sign_in ? "開啟既有登入流程" : "登入 AWS Events",
      disabled: false,
    };
  if (state.error === "connection_unavailable")
    return {
      title: "暫時無法確認官方連線；請稍後按右上角重新讀取。",
      button: "登入 AWS Events",
      disabled: true,
    };
  if (state.pending_sign_in)
    return {
      title: "登入尚未完成；完成 AWS 登入後，議程會自動載入。",
      button: "開啟既有登入流程",
      disabled: false,
    };
  return {
    title: "登入 AWS Events，載入你的活動可存取的官方議程。",
    button: "登入 AWS Events",
    disabled: false,
  };
}

const safeErrors = new Set([
  "sign_in_required",
  "callback_unavailable",
  "not_registered",
  "rate_limited",
  "catalog_unavailable",
]);
export function safeConnectionError(value) {
  return safeErrors.has(value) ? value : "connection_unavailable";
}

export function catalogFailureMessage(code, hasRecords = false) {
  const retained = hasRecords
    ? "目前保留上次議程與本機安排。"
    : "本機安排仍保留，暫不判定場次是否已移除。";
  if (code === "sign_in_required")
    return `請先登入 AWS Events，才能載入官方議程。${retained}`;
  if (code === "not_registered")
    return `這個帳號尚未取得活動存取權；請確認 re:Invent 註冊狀態。${retained}`;
  if (code === "rate_limited")
    return `官方服務目前限流，請稍後重試。${retained}`;
  return `官方議程暫時無法載入，請稍後重試。${retained}`;
}

export function sourceTimingNote(source) {
  return source === "aws_events_api"
    ? "時間依官方 API 的場次資料呈現；未提供的時間保持未知，不推算其他重複時段。"
    : "目前為正規化快取時段，非完整官方重複時段集。";
}

export function createOfficialConnection({
  request = fetch,
  onChange = () => {},
  onConnected = () => {},
  schedule = setTimeout,
  cancel = clearTimeout,
} = {}) {
  let state = {
    checking: true,
    checked: false,
    connected: false,
    pending_sign_in: false,
    error: null,
    callback_available: null,
    expiring: false,
  };
  let active = null,
    timer = null,
    stopped = false,
    starting = false;
  const emit = () => onChange({ ...state, starting });
  const schedulePoll = () => {
    if (timer !== null) cancel(timer);
    timer = null;
    if (!stopped && state.pending_sign_in && !state.connected)
      timer = schedule(() => {
        timer = null;
        void refresh();
      }, 3000);
  };
  function refresh() {
    if (active) return active;
    if (stopped) return Promise.resolve({ ...state });
    state.checking = true;
    emit();
    active = (async () => {
      let becameConnected = false;
      try {
        const response = await request("/api/auth/status", {
          cache: "no-store",
        });
        if (!response.ok) throw Error();
        const data = await response.json();
        if (
          data.provider !== "aws_events_api" ||
          typeof data.connected !== "boolean"
        )
          throw Error();
        // Same rule as web.py's /api/status: an expired token that cannot refresh is not signed in,
        // although the server still holds it (auth_status "refresh_required").
        const connected =
          data.connected &&
          (typeof data.expires_at !== "number" ||
            data.expires_at * 1000 > Date.now() ||
            data.refreshable === true);
        becameConnected = connected && !state.connected;
        state = {
          checking: false,
          checked: true,
          expiring: state.expiring && connected,
          connected,
          pending_sign_in: data.pending_sign_in === true,
          callback_available: data.callback_available === true,
          error: data.error ? safeConnectionError(data.error) : null,
        };
      } catch {
        state = {
          ...state,
          checking: false,
          checked: true,
          connected: false,
          error: "connection_unavailable",
        };
      }
      if (!stopped) {
        emit();
        if (becameConnected) await onConnected();
        schedulePoll();
      }
      return { ...state };
    })().finally(() => {
      active = null;
    });
    return active;
  }
  async function start() {
    if (starting || stopped || (state.connected && !state.expiring)) return null;
    starting = true;
    emit();
    try {
      const response = await request("/api/auth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) {
        state.error = safeConnectionError(data.error);
        return null;
      }
      const url = new URL(data.authorization_url);
      if (url.protocol !== "https:" || url.username || url.password)
        throw Error();
      state.pending_sign_in = true;
      state.error = null;
      return url.href;
    } catch {
      state.error = "connection_unavailable";
      return null;
    } finally {
      starting = false;
      emit();
      schedulePoll();
    }
  }
  return {
    refresh,
    start,
    requireSignIn(error = "sign_in_required") {
      state = {
        ...state,
        connected: false,
        pending_sign_in: false,
        error: safeConnectionError(error),
      };
      emit();
      schedulePoll();
    },
    /**
     * The server's own view of the sign-in (from Copilot's status poll): signed out or expired
     * re-enables "登入 AWS Events" (also after a failed auth check); about to expire offers "再次登入";
     * signed in elsewhere re-checks.
     */
    applyStatus({ signed_in, soon } = {}) {
      if (stopped || typeof signed_in !== "boolean") return;
      if (!signed_in) {
        if (state.connected || state.expiring) {
          state = {
            ...state,
            connected: false,
            expiring: false,
            pending_sign_in: false,
            error: "sign_in_required",
          };
          emit();
          schedulePoll();
        } else if (state.error === "connection_unavailable") {
          // The poll got an answer from this service, so an earlier failed auth check no longer
          // applies: clear it and give the sign-in button back.
          state = { ...state, checking: false, checked: true, error: "sign_in_required" };
          emit();
          schedulePoll();
        }
        return;
      }
      if (!state.connected) {
        void refresh();
        return;
      }
      if (state.expiring !== !!soon) {
        state.expiring = !!soon;
        emit();
      }
    },
    stop() {
      stopped = true;
      if (timer !== null) cancel(timer);
      timer = null;
    },
    snapshot: () => ({ ...state }),
  };
}
