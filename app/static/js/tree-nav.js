/**
 * FlowForge — tree-nav.js
 *
 * Дерево узлов проекта (титульный лист как корень, страницы и канвасы
 * вперемешку — одно дерево, а не переключатель режимов). Рекурсивная
 * отрисовка, сворачивание веток, контекстное меню (создать/переименовать/
 * удалить), drag-and-drop для смены родителя. Не делает HTTP-запросов сам —
 * получает дерево целиком через loadTree() и уведомляет editor.js о выборе
 * узла через onSelect-колбэк (задаётся в init()), не привязываясь к
 * конкретной реализации того, что показывать справа.
 */
window.FF = window.FF || {};

window.FF.tree = (function () {
  "use strict";

  let flatNodes = [];      // все узлы проекта одним плоским списком с backend
  let childrenByParent = {};
  let expandedIds = new Set();
  let activeNodeId = null;
  let onSelect = () => {};
  let rootNodeId = null;
  // Node.public_dict() не несёт project_id (незачем дублировать его в
  // каждом узле дерева) — id проекта храним здесь явно, из init().
  let currentProjectId = null;

  function _icon(kind) {
    return kind === "canvas" ? "◇" : "▤";
  }

  // Право на правку дерева решает сервер (FF_PROJECT.can.edit) — фронт
  // лишь не показывает кнопки тем, кто всё равно получит 403.
  function _canEdit() {
    return !!(window.FF_PROJECT && window.FF_PROJECT.can && window.FF_PROJECT.can.edit);
  }

  function _rebuildIndex() {
    childrenByParent = {};
    flatNodes.forEach((node) => {
      const key = node.parent_id || "__root__";
      (childrenByParent[key] = childrenByParent[key] || []).push(node);
    });
    Object.values(childrenByParent).forEach((list) => list.sort((a, b) => a.position - b.position));
  }

  async function loadTree(projectId) {
    currentProjectId = projectId;
    flatNodes = await FF.api.get(`/api/projects/${projectId}/tree`);
    rootNodeId = (flatNodes.find((n) => !n.parent_id) || {}).id || null;
    _rebuildIndex();
    if (rootNodeId) expandedIds.add(rootNodeId);
    render();
    return rootNodeId;
  }

  function render() {
    const root = document.getElementById("tree-root");
    root.innerHTML = "";
    if (rootNodeId) root.appendChild(_renderNode(rootNodeId, 0));
  }

  function _renderNode(nodeId, depth) {
    const node = flatNodes.find((n) => n.id === nodeId);
    if (!node) return document.createDocumentFragment();

    const wrapper = document.createElement("div");

    const row = document.createElement("div");
    row.className = "tree-node-row" + (nodeId === activeNodeId ? " active" : "");
    row.setAttribute("data-node-id", nodeId);
    row.setAttribute("draggable", node.parent_id ? "true" : "false"); // корень никуда не перетаскивают

    const children = childrenByParent[nodeId] || [];
    const hasChildren = children.length > 0;
    const isExpanded = expandedIds.has(nodeId);

    const toggle = document.createElement("span");
    toggle.className = "tree-node-toggle" + (isExpanded ? " is-expanded" : "");
    toggle.textContent = hasChildren ? "▸" : "";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!hasChildren) return;
      if (isExpanded) expandedIds.delete(nodeId); else expandedIds.add(nodeId);
      render();
    });

    const icon = document.createElement("span");
    icon.className = "tree-node-icon";
    icon.textContent = _icon(node.kind);

    const title = document.createElement("span");
    title.className = "tree-node-title";
    title.textContent = node.title;

    const addBtn = document.createElement("span");
    addBtn.className = "tree-node-add-btn";
    addBtn.textContent = "＋";
    addBtn.title = FF.t("ui.tree.add_child");
    addBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _openContextMenu(e, nodeId, /* forceCreateMenu */ true);
    });

    row.appendChild(toggle);
    row.appendChild(icon);
    row.appendChild(title);
    if (node.kind === "page" && _canEdit()) row.appendChild(addBtn);

    row.addEventListener("click", () => selectNode(nodeId));
    row.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      _openContextMenu(e, nodeId, false);
    });
    _wireDrag(row, nodeId);

    wrapper.appendChild(row);

    if (hasChildren && isExpanded) {
      const childrenBox = document.createElement("div");
      childrenBox.className = "tree-node-children";
      children.forEach((child) => childrenBox.appendChild(_renderNode(child.id, depth + 1)));
      wrapper.appendChild(childrenBox);
    }

    return wrapper;
  }

  function selectNode(nodeId) {
    activeNodeId = nodeId;
    render();
    onSelect(nodeId);
  }

  // ------------------------------------------------------------------
  // Drag-and-drop: перетащить узел на другую страницу — сменить родителя
  // ------------------------------------------------------------------
  function _wireDrag(row, nodeId) {
    row.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", nodeId);
      e.dataTransfer.effectAllowed = "move";
    });
    row.addEventListener("dragover", (e) => {
      const node = flatNodes.find((n) => n.id === nodeId);
      if (node && node.kind === "page") { e.preventDefault(); row.style.background = "var(--accent-primary-soft)"; }
    });
    row.addEventListener("dragleave", () => { row.style.background = ""; });
    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      row.style.background = "";
      const draggedId = e.dataTransfer.getData("text/plain");
      const targetNode = flatNodes.find((n) => n.id === nodeId);
      if (!draggedId || draggedId === nodeId || !targetNode || targetNode.kind !== "page") return;
      try {
        await FF.api.patch(`/api/nodes/${draggedId}/move`, { parent_id: nodeId });
        await _reload();
      } catch (err) {
        alert(err.message);
      }
    });
  }

  async function _reload() {
    if (currentProjectId) await loadTree(currentProjectId);
  }

  // ------------------------------------------------------------------
  // Контекстное меню: создать страницу/канвас, переименовать, удалить
  // ------------------------------------------------------------------
  function _openContextMenu(event, nodeId, forceCreateOnly) {
    const node = flatNodes.find((n) => n.id === nodeId);
    const menu = document.getElementById("tree-context-menu");
    menu.innerHTML = "";

    const addItem = (labelKey, handler) => {
      const item = document.createElement("div");
      item.className = "context-menu-item";
      item.textContent = FF.t(labelKey);
      item.addEventListener("click", () => { menu.style.display = "none"; handler(); });
      menu.appendChild(item);
    };

    if (_canEdit()) {
      if (node.kind === "page") {
        addItem("ui.tree.new_page", () => _createChild(nodeId, "page"));
        addItem("ui.tree.new_canvas", () => _createChild(nodeId, "canvas"));
      }
      if (!forceCreateOnly) {
        addItem("ui.tree.rename", () => _renamePrompt(nodeId, node.title));
        if (node.parent_id) addItem("ui.tree.delete", () => _deleteConfirm(nodeId));
      }
    }
    if (menu.children.length === 0) return; // нечего показывать — меню не открываем

    menu.style.left = event.clientX + "px";
    menu.style.top = event.clientY + "px";
    menu.style.display = "block";
  }

  document.addEventListener("click", () => {
    document.getElementById("tree-context-menu").style.display = "none";
  });

  async function _createChild(parentId, kind) {
    // Модалка с карточками типа и полем названия — вместо prompt():
    // create-node.js решает только UI, созданием узла владеет этот модуль.
    if (window.FF.createNode) {
      const data = await FF.createNode.open(parentId, kind);
      if (!data) return;
      kind = data.kind;
      try {
        const node = await FF.api.post("/api/nodes", { parent_id: parentId, kind: kind, title: data.title });
        expandedIds.add(parentId);
        await _reload();
        selectNode(node.id);
      } catch (err) {
        alert(err.message);
      }
      return;
    }
    try {
      const node = await FF.api.post("/api/nodes", { parent_id: parentId, kind });
      expandedIds.add(parentId);
      await _reload();
      selectNode(node.id);
    } catch (err) {
      alert(err.message);
    }
  }

  async function _renamePrompt(nodeId, currentTitle) {
    const title = window.prompt(FF.t("ui.tree.rename_prompt"), currentTitle);
    if (!title || title === currentTitle) return;
    try {
      await FF.api.patch(`/api/nodes/${nodeId}`, { title });
      await _reload();
    } catch (err) {
      alert(err.message);
    }
  }

  async function _deleteConfirm(nodeId) {
    if (!window.confirm(FF.t("ui.tree.delete_confirm"))) return;
    try {
      await FF.api.del(`/api/nodes/${nodeId}`);
      if (activeNodeId === nodeId) selectNode(rootNodeId);
      await _reload();
    } catch (err) {
      alert(err.message);
    }
  }

  function setActive(nodeId) {
    activeNodeId = nodeId;
    render();
  }

  function init(options) {
    onSelect = options.onSelect || (() => {});
  }

  // Для упоминаний [[type:id|text]] в markdown — плоский список узлов.
  function getAllNodes() { return Array.from(flatNodes.values()); }

  return { init, loadTree, selectNode, setActive, getAllNodes };
})();
