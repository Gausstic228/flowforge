/**
 * FlowForge — клиентский i18n.
 *
 * Ни один текст интерфейса не зашит в JS-файлы буквенно: разметка
 * помечает место атрибутом data-i18n="ключ.из.json", а этот модуль
 * подставляет значение из window.FF_I18N (словарь текущего языка,
 * отданный сервером в base.html из translations/<lang>.json).
 *
 * Динамический JS, которому нужен текст вне разметки, вызывает
 * FF.t('ключ', {var: 'значение'}) — та же подстановка {var}, что и
 * на backend в app/services/i18n.py.
 */
(function () {
  "use strict";

  const DICT = window.FF_I18N || {};

  /**
   * FF.t(key, vars) — перевод по ключу с подстановкой {переменных}.
   * Если ключа нет в словаре — возвращает сам ключ (видно в интерфейсе,
   * что перевод не найден, вместо тихой пустоты).
   */
  function t(key, vars) {
    let template = DICT[key];
    if (template === undefined) {
      return key;
    }
    if (vars) {
      for (const name in vars) {
        template = template.split("{" + name + "}").join(String(vars[name]));
      }
    }
    return template;
  }

  /**
   * Применяет переводы ко всем [data-i18n] в переданном корне (по
   * умолчанию — ко всему документу). Вызывается один раз при загрузке
   * страницы и повторно для любого фрагмента, который JS вставил в
   * DOM динамически (канвас генерирует блоки/порты на лету).
   */
  function applyTranslations(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      el.textContent = t(key);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      el.setAttribute("placeholder", t(key));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      el.setAttribute("title", t(key));
    });
  }

  function renderLangSwitch() {
    const host = document.getElementById("lang-switch");
    if (!host) return;

    const languages = window.FF_LANGUAGES || [];
    if (languages.length < 2) return;

    const current = window.FF_LANG || "ru";
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Language");
    select.style.cssText =
      "background:var(--bg-panel-raised);border:1px solid var(--border-subtle);" +
      "color:var(--text-primary);border-radius:8px;padding:6px 10px;font-size:13px;";

    languages.forEach((lang) => {
      const opt = document.createElement("option");
      opt.value = lang.code;
      opt.textContent = lang.name;
      opt.selected = lang.code === current;
      select.appendChild(opt);
    });

    select.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("lang", select.value);
      document.cookie =
        "flowforge_lang=" + select.value + ";path=/;max-age=" + 60 * 60 * 24 * 365;
      window.location.href = url.toString();
    });

    host.appendChild(select);
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTranslations(document);
    renderLangSwitch();
  });

  // Публичный интерфейс для остальных скриптов канваса/дашборда.
  window.FF = window.FF || {};
  window.FF.t = t;
  window.FF.applyTranslations = applyTranslations;
})();
