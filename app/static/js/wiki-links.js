/**
 * FlowForge — wiki-links.js
 *
 * Синтаксис ссылок внутри markdown-страниц: [[type:id]] или
 * [[type:id|Текст ссылки]], где type — "page", "block" или "suggestion".
 * Рендерится как обычная кликабельная markdown-ссылка ПЕРЕД тем, как
 * marked.js разберёт весь текст — так они получают полноценную HTML-обвязку
 * (<a>, экранирование) от того же парсера, а не собираются вручную поверх
 * готового HTML, где легко случайно сломать вложенность тегов.
 *
 * Экранирование кода: [[...]], написанный человеком буквально как пример
 * внутри ```тройных кавычек```, не должен превращаться в ссылку — текст
 * сначала режется на "код"/"не код" по regex тройных бэктиков, замена
 * идёт только по кускам вне кода, потом всё склеивается обратно.
 */
window.FF = window.FF || {};

window.FF.wikiLinks = (function () {
  "use strict";

  // [[type:id]] или [[type:id|alias]] — id: 32 hex-символа (наш формат id).
  // Группа |alias помечена как ?, иначе базовый синтаксис БЕЗ alias вообще
  // не матчился бы — а именно он самый частый в тексте.
  const WIKI_LINK_RE = /\[\[(page|block|suggestion):([0-9a-f]{32})(?:\|([^\]]+))?\]\]/g;
  const CODE_FENCE_RE = /(```[\s\S]*?```|`[^`\n]*`)/g;

  const _titleCache = new Map(); // "type:id" -> название (или null, если объект не найден)

  function _cacheKey(type, id) {
    return type + ":" + id;
  }

  /**
   * Заменяет [[type:id|alias?]] на markdown-ссылку с кастомной схемой
   * wikilink://type/id — так marked.js оборачивает её в обычный <a href="...">,
   * а сам href мы уже сами перехватываем в приложении (см. resolveHrefClick).
   * Название, если alias не указан, берётся из уже прогретого кэша
   * (см. prefetchTitles) — при первой отрисовке страницы alias отсутствует,
   * значит показываем id как временную подпись до её резолва.
   */
  function _replaceOutsideCode(text) {
    return text
      .split(CODE_FENCE_RE)
      .map((chunk, index) => {
        // Чётные индексы после split по CODE_FENCE_RE — это код, не трогаем.
        if (index % 2 === 1) return chunk;
        return chunk.replace(WIKI_LINK_RE, (_match, type, id, alias) => {
          const label = alias || _titleCache.get(_cacheKey(type, id)) || id.slice(0, 8) + "…";
          return `[${label}](wikilink://${type}/${id})`;
        });
      })
      .join("");
  }

  /**
   * Собирает все [[type:id]] из текста, чтобы заранее запросить их
   * настоящие названия одним batch-запросом — иначе первая отрисовка
   * страницы показывала бы голые id вместо человеческих подписей.
   */
  async function prefetchTitles(markdownText) {
    const refs = [];
    for (const match of markdownText.matchAll(WIKI_LINK_RE)) {
      const [, type, id, alias] = match;
      if (!alias && !_titleCache.has(_cacheKey(type, id))) {
        refs.push({ type, id });
      }
    }
    if (refs.length === 0) return false;

    try {
      const resolved = await FF.api.post("/api/nodes/resolve-refs", { refs });
      resolved.forEach((entry) => {
        _titleCache.set(_cacheKey(entry.type, entry.id), entry.title);
      });
      return true;
    } catch (err) {
      console.error("Failed to resolve wiki-links:", err);
      return false;
    }
  }

  /**
   * Рендерит markdown в HTML с уже подставленными wiki-ссылками. Вызывающий
   * код (editor.js) отвечает за то, чтобы прогнать prefetchTitles() один
   * раз до первого рендера и повторно вызвать render() после — так подписи
   * подтягиваются без полной перезагрузки, без блокировки первого показа.
   */
  function render(markdownText) {
    const withLinks = _replaceOutsideCode(markdownText || "");
    const html = window.marked.parse(withLinks);
    return _markWikilinkAnchors(html);
  }

  /**
   * marked.js уже сгенерировал <a href="wikilink://type/id">название</a> —
   * помечаем такие ссылки классом (для стиля из main.css) и раскладываем
   * href на data-атрибуты, чтобы клик перехватывался без парсинга строки.
   */
  function _markWikilinkAnchors(html) {
    const container = document.createElement("div");
    container.innerHTML = html;
    container.querySelectorAll('a[href^="wikilink://"]').forEach((a) => {
      const [, type, id] = a.getAttribute("href").match(/^wikilink:\/\/([a-z]+)\/([0-9a-f]{32})$/) || [];
      if (!type) return;
      a.classList.add("wiki-link");
      a.setAttribute("data-wiki-type", type);
      a.setAttribute("data-wiki-id", id);
      a.removeAttribute("href");
      a.setAttribute("href", "#");
    });
    return container.innerHTML;
  }

  /**
   * Вставляет [[type:id]] в текстовое поле на месте курсора — используется
   * панелью "Связать с объектом" (см. editor.js), а не набирается вручную
   * человеком каждый раз, хотя ручной ввод синтаксиса тоже работает.
   */
  function insertAtCursor(textarea, type, id, label) {
    const token = `[[${type}:${id}|${label}]]`;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const before = textarea.value.slice(0, start);
    const after = textarea.value.slice(end);
    textarea.value = before + token + after;
    const cursor = start + token.length;
    textarea.setSelectionRange(cursor, cursor);
    textarea.focus();
  }

  return { render, prefetchTitles, insertAtCursor };
})();
