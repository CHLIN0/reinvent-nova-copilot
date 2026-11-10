// Plain-words text for the server's error codes (web.py _ERRORS), in the page's language.
const SERVICE_ERRORS = {
  signin_expired: "登入已過期，請從頁面上方重新登入。",
  forbidden: "AWS Events 拒絕了這個要求。",
  rate_limited: "AWS Events 目前忙碌，請稍候一分鐘再試。",
  model_unavailable: "Nova 暫時無法使用；你的安排與官方行程不受影響，請稍後再試。",
  server_error: "本機的 Nova Copilot 服務發生錯誤，請再試一次；若重複發生請重新啟動。",
};
export const serviceErrorText = (code) => SERVICE_ERRORS[code] || "";
