/**
 * FlowForge — HTTP-клиент.
 *
 * Тонкая обёртка над fetch(): подставляет JSON-заголовки, парсит
 * ответ, и если сервер вернул ошибку — бросает Error с текстом,
 * который уже пришёл ПЕРЕВЕДЁННЫМ с backend (см. app/services/i18n.py,
 * там сообщения собираются через t() на языке текущего запроса).
 * Этот файл сам не хранит ни одной фразы на человеческом языке.
 */
window.FF = window.FF || {};

window.FF.api = (function () {
  "use strict";

  async function request(method, url, body) {
    const options = {
      method,
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
    };
    if (body !== undefined) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const payload = isJson ? await response.json() : await response.text();

    if (!response.ok) {
      const message =
        (isJson && payload && (payload.message || payload.description)) ||
        (typeof payload === "string" ? payload : response.statusText);
      throw new Error(message);
    }
    return payload;
  }

  return {
    get: (url) => request("GET", url),
    post: (url, body) => request("POST", url, body || {}),
    put: (url, body) => request("PUT", url, body || {}),
    patch: (url, body) => request("PATCH", url, body || {}),
    del: (url) => request("DELETE", url),
  };
})();
