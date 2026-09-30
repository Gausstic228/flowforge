/**
 * FlowForge — editor.js
 *
 * Точка сборки полноэкранного редактора. Инициализирует дерево слева и
 * панели настроек/предложений, слушает выбор узла из дерева и монтирует в
 * рабочую область либо markdown-редактор (kind=page), либо canvas.js
 * (kind=canvas) — само дерево и панели не знают, что именно показывается
 * справа, этот файл единственный решает переключение.
 */
window.FF = window.FF || {};

window.FF.editor = (function () {
  "use strict";

  const workspaceBody = document.getElementById("workspace-body");
  const workspaceTitle = document.getElementById("workspace-title");

  let currentNode = null; // последний загруженный узел целиком (public_dict_with_content)
  let saveTimer = null;
  const SAVE_DEBOUNCE_MS = 800;

  // ------------------------------------------------------------------
  // Переключение между markdown-страницей и канвасом
  // ------------------------------------------------------------------
  async function openNode(nodeId) {
    // Незавершённая правка текста не должна потеряться при уходе со
    // страницы — сохраняем немедленно, не дожидаясь дебаунса.
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; _flushPageSave(); }
    if (window.FF.canvas) FF.canvas.unmount();

    const node = await FF.api.get(`/api/nodes/${nodeId}`);
    currentNode = node;
    workspaceTitle.textContent = node.title;
    FF.panel.setCurrentNode(nodeId);
    FF.tree.setActive(nodeId);
    // На мобильном дерево — оверлей: после выбора узла убираем его,
    // чтобы сразу показать содержимое.
    document.getElementById("editor-tree").classList.remove("is-mobile-open");
    if (window.matchMedia("(max-width: 960px)").matches) {
      document.getElementById("btn-expand-tree").style.display = "inline-flex";
    }

    document.getElementById("validation-panel").style.display = "none";
    document.getElementById("suggestions-panel").style.display = "none";

    if (node.kind === "canvas") {
      FF.canvas.mount(workspaceBody, node, FF.panel.getProject());
    } else {
      _mountPageEditor(node);
    }

    const url = new URL(window.location.href);
    const base = window.FF_PROJECT.slug ? "/" + window.FF_PROJECT.slug : "/p/" + window.FF_PROJECT.id;
    window.history.replaceState({}, "", nodeId === window.FF_ROOT_NODE_ID ? base : base + "/" + nodeId);
  }

  /** Перезагружает текущий узел с сервера — вызывается после принятия предложения. */
  function reloadCurrentNode() {
    if (currentNode) openNode(currentNode.id);
  }

  // ------------------------------------------------------------------
  // Markdown-страница: textarea слева, живой предпросмотр справа
  // ------------------------------------------------------------------
  let sourceEl = null, previewEl = null;

  function _mountPageEditor(node) {
    workspaceBody.innerHTML = document.getElementById("tpl-page-editor").innerHTML;
    sourceEl = workspaceBody.querySelector("#page-source");
    previewEl = workspaceBody.querySelector("#page-preview");
    const canEditNow = FF.panel.getProject().can.edit;

    sourceEl.value = node.content || "";
    sourceEl.disabled = !canEditNow;
    if (!canEditNow) sourceEl.parentElement.style.display = "none";
    workspaceBody.querySelector(".page-editor").classList.toggle("is-preview-only", !canEditNow);

    _renderPreview(sourceEl.value);
    sourceEl.addEventListener("input", () => {
      _renderPreview(sourceEl.value);
      clearTimeout(saveTimer);
      saveTimer = setTimeout(_flushPageSave, SAVE_DEBOUNCE_MS);
    });

    _wirePageToolbar(sourceEl, canEditNow);
    _wireWikiLinkClicks(previewEl);
  }

  // Тулбар markdown: жирный/курсив/заголовок/ссылка + упоминания объектов
  // проекта. Упоминание вставляется как [[page:ID|Название]] — ровно тот
  // формат, который разрешает wiki-links.js (kind + id + подпись через |).
  function _wirePageToolbar(sourceEl, canEditNow) {
    const toolbar = workspaceBody.querySelector("#page-editor-toolbar");
    const select = workspaceBody.querySelector("#mention-select");
    if (toolbar && !canEditNow) toolbar.style.display = "none";

    const wrap = (before, after, placeholder) => {
      const start = sourceEl.selectionStart, end = sourceEl.selectionEnd;
      const text = sourceEl.value;
      const selected = text.slice(start, end) || placeholder;
      sourceEl.value = text.slice(0, start) + before + selected + after + text.slice(end);
      sourceEl.focus();
      sourceEl.selectionStart = start + before.length;
      sourceEl.selectionEnd = start + before.length + selected.length;
      sourceEl.dispatchEvent(new Event("input"));
    };
    if (toolbar) toolbar.querySelectorAll("[data-md]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const kind = btn.dataset.md;
        if (kind === "bold") wrap("**", "**", FF.t("ui.editor.bold"));
        if (kind === "italic") wrap("*", "*", FF.t("ui.editor.italic"));
        if (kind === "heading") wrap("## ", "", FF.t("ui.editor.heading"));
        if (kind === "link") wrap("[", "](https://)", FF.t("ui.editor.link"));
      });
    });

    if (!select || !window.FF.tree || !window.FF.tree.getAllNodes) return;
    FF.tree.getAllNodes().forEach((node) => {
      const opt = document.createElement("option");
      opt.value = `${node.kind}:${node.id}`;
      opt.textContent = (node.kind === "canvas" ? "◇ " : "▤ ") + node.title;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      if (!select.value) return;
      const [kind, id] = select.value.split(":");
      const node = FF.tree.getAllNodes().find((n) => String(n.id) === id);
      const md = `[[${kind}:${id}|${node ? node.title : "link"}]]`;
      const start = sourceEl.selectionStart, end = sourceEl.selectionEnd;
      sourceEl.value = sourceEl.value.slice(0, start) + md + sourceEl.value.slice(end);
      sourceEl.selectionStart = sourceEl.selectionEnd = start + md.length;
      sourceEl.focus();
      sourceEl.dispatchEvent(new Event("input"));
      select.value = "";
    });
  }

  async function _renderPreview(markdownText) {
    const changed = await FF.wikiLinks.prefetchTitles(markdownText);
    previewEl.innerHTML = FF.wikiLinks.render(markdownText);
    if (changed) previewEl.innerHTML = FF.wikiLinks.render(markdownText); // подписи подтянулись — перерисовать с ними
    _wireWikiLinkClicks(previewEl);
  }

  async function _flushPageSave() {
    if (!currentNode || currentNode.kind !== "page" || !sourceEl) return;
    try {
      await FF.api.put(`/api/nodes/${currentNode.id}/content`, { content: sourceEl.value });
    } catch (err) {
      console.error("Failed to save page:", err);
    }
  }

  /** Клик по [[type:id]]-ссылке — переходит на узел дерева или открывает предложение. */
  function _wireWikiLinkClicks(container) {
    container.querySelectorAll("a.wiki-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const type = a.getAttribute("data-wiki-type");
        const id = a.getAttribute("data-wiki-id");
        if (type === "page") {
          openNode(id);
        } else if (type === "block") {
          _openBlockOwner(id);
        } else if (type === "suggestion") {
          document.getElementById("btn-suggestions").click();
        }
      });
    });
  }

  /** Ссылка на блок открывает узел-канвас, которому он принадлежит (node_id из резолвера). */
  async function _openBlockOwner(blockId) {
    try {
      const [resolved] = await FF.api.post("/api/nodes/resolve-refs", { refs: [{ type: "block", id: blockId }] });
      if (resolved && resolved.node_id) await openNode(resolved.node_id);
    } catch (err) {
      console.error("Failed to open block owner:", err);
    }
  }

  // ------------------------------------------------------------------
  // Дерево: сворачивание/разворачивание панели
  // ------------------------------------------------------------------
  function _wireTreeCollapse() {
    const tree = document.getElementById("editor-tree");
    const expandBtn = document.getElementById("btn-expand-tree");
    document.getElementById("btn-collapse-tree").addEventListener("click", () => {
      tree.classList.add("is-collapsed");
      tree.classList.remove("is-mobile-open");
      expandBtn.style.display = "inline-flex";
    });
    expandBtn.addEventListener("click", () => {
      tree.classList.remove("is-collapsed");
      // На десктопе дерево и так видимо; is-mobile-open нужен только на
      // узком экране, где оно скрыто по умолчанию (см. @media в main.css).
      if (window.matchMedia("(max-width: 960px)").matches) tree.classList.add("is-mobile-open");
      expandBtn.style.display = "none";
    });
  }

  // ------------------------------------------------------------------
  // Инициализация страницы
  // ------------------------------------------------------------------
  async function _init() {
    FF.panel.init(window.FF_PROJECT);
    FF.tree.init({ onSelect: openNode });
    _wireTreeCollapse();

    await FF.tree.loadTree(window.FF_PROJECT.id);
    await openNode(window.FF_OPEN_NODE_ID || window.FF_ROOT_NODE_ID);
  }

  document.addEventListener("DOMContentLoaded", _init);

  return { openNode, reloadCurrentNode };
})();
