/**
 * FlowForge — canvas.js
 *
 * Интерактивность свободного холста: drag блоков, рисование связи от точки
 * к точке, панорамирование и зум, выбор блока и его инспектор (форма, цвет,
 * подпись — не порты: программа не оценивает форму блока, только рисует
 * то, что выбрал человек). Структура диаграммы меняется единственным
 * путём — patchNode(...) отправляет операции на POST /<id>/patch, сервер
 * применяет их через graph_validator.apply_patch и рассылает diagram_state
 * обратно всей комнате (включая автора) — поэтому здесь нет "оптимистичного"
 * применения структурных изменений до подтверждения сервером, кроме явного
 * режима предложений (suggestModeOn), где подтверждения от сервера в
 * принципе не будет, пока предложение не примут.
 *
 * Экспортирует window.FF.canvas.mount(container, node, project) — editor.js
 * вызывает это, когда пользователь открывает узел kind=canvas в дереве, и
 * unmount() при переходе на другой узел (чтобы отключить сокет и слушатели).
 */
window.FF = window.FF || {};

window.FF.canvas = (function () {
  "use strict";

  let svg, viewport, blocksLayer, connectorsLayer, cursorsLayer;
  let nodeId, project, canEdit;
  let graphState = { blocks: [], connectors: [] };
  let validation = { issues: [] };
  let selectedBlockId = null;
  let suggestModeOn = false;
  let pendingOps = [];
  let mounted = false;

  const camera = { x: 0, y: 0, scale: 1 };

  // ------------------------------------------------------------------
  // Монтирование/размонтирование — editor.js вызывает при смене узла
  // ------------------------------------------------------------------
  function mount(container, node, projectRef) {
    nodeId = node.id;
    project = projectRef;
    canEdit = project.can.edit;
    graphState = node.diagram || { blocks: [], connectors: [] };
    validation = { issues: [] };
    selectedBlockId = null;
    suggestModeOn = false;
    pendingOps = [];
    camera.x = 0; camera.y = 0; camera.scale = 1;

    container.innerHTML = document.getElementById("tpl-canvas-editor").innerHTML;
    svg = container.querySelector("#svg-canvas");
    viewport = container.querySelector("#canvas-viewport");
    blocksLayer = container.querySelector("#blocks-layer");
    connectorsLayer = container.querySelector("#connectors-layer");
    cursorsLayer = container.querySelector("#cursors-layer");

    _wireCamera();
    _wireToolbar(container);
    _wireConnectorClicks();
    FF.socket.connect(nodeId);
    _wireSocket();
    mounted = true;
    rerender();
    FF.applyTranslations(container);
  }

  function unmount() {
    if (!mounted) return;
    FF.socket.disconnect();
    mounted = false;
  }

  function currentValidation() {
    return validation;
  }

  // ------------------------------------------------------------------
  // Патч диаграммы — единственный путь изменить структуру. suggestModeOn
  // выключает немедленную отправку и копит операции локально вместо неё.
  // ------------------------------------------------------------------
  async function patchNode(ops, label) {
    if (suggestModeOn) {
      pendingOps.push(...ops);
      _applyOpsLocally(ops);
      return;
    }
    try {
      const payload = await FF.api.post(`/api/nodes/${nodeId}/patch`, { patch: ops });
      graphState = payload.graph;
      validation = payload.validation;
      rerender();
    } catch (err) {
      alert(err.message);
    }
  }

  /** Оптимистичное применение ТОЛЬКО для предпросмотра черновика предложения себе — не рассылается. */
  function _applyOpsLocally(ops) {
    ops.forEach((op) => {
      if (op.op === "edit_block") {
        const block = graphState.blocks.find((b) => b.id === op.id);
        if (block) Object.assign(block, _pick(op, ["title", "shape", "color", "x", "y", "width", "height"]));
      } else if (op.op === "delete_block") {
        graphState.blocks = graphState.blocks.filter((b) => b.id !== op.id);
        graphState.connectors = graphState.connectors.filter(
          (c) => c.from_block !== op.id && c.to_block !== op.id
        );
      } else if (op.op === "add_connector") {
        graphState.connectors.push({
          id: "pending-" + Date.now() + Math.random(),
          from_block: op.from_block, to_block: op.to_block,
          from_point: op.from_point || null, to_point: op.to_point || null,
          label: op.label || "", color: op.color || "#5c6178",
          dashed: !!op.dashed, arrow: op.arrow !== false,
        });
      } else if (op.op === "delete_connector") {
        graphState.connectors = graphState.connectors.filter((c) => c.id !== op.id);
      }
    });
    rerender();
  }

  function _pick(obj, keys) {
    const result = {};
    keys.forEach((k) => { if (k in obj) result[k] = obj[k]; });
    return result;
  }

  // ------------------------------------------------------------------
  // Камера: панорамирование и зум (то же линейное transform, что и раньше)
  // ------------------------------------------------------------------
  function _applyCameraTransform() {
    viewport.setAttribute("transform", `translate(${camera.x}, ${camera.y}) scale(${camera.scale})`);
  }

  function _screenToWorld(clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return { x: (clientX - rect.left - camera.x) / camera.scale, y: (clientY - rect.top - camera.y) / camera.scale };
  }

  let isPanning = false, panStart = null;

  function _wireCamera() {
    svg.addEventListener("mousedown", (e) => {
      if (e.target === svg || e.target === viewport) {
        isPanning = true;
        panStart = { x: e.clientX - camera.x, y: e.clientY - camera.y };
        svg.classList.add("panning");
        _selectBlock(null);
      }
    });
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
      const newScale = Math.min(2.5, Math.max(0.3, camera.scale * factor));
      const world = _screenToWorld(e.clientX, e.clientY);
      camera.scale = newScale;
      const rect = svg.getBoundingClientRect();
      camera.x = e.clientX - rect.left - world.x * newScale;
      camera.y = e.clientY - rect.top - world.y * newScale;
      _applyCameraTransform();
    }, { passive: false });
  }

  // Панорамирование держится на window-слушателях (мышь может уйти за
  // пределы SVG во время перетаскивания камеры), а window никогда не
  // пересоздаётся — в отличие от svg выше, эти два регистрируются РОВНО
  // ОДИН РАЗ на уровне модуля (не внутри _wireCamera, которая вызывается
  // при каждом mount()), иначе каждый переход между узлами дерева
  // добавлял бы ещё одну пару обработчиков, которая никогда не снимается.
  window.addEventListener("mousemove", (e) => {
    if (!mounted || !isPanning) return;
    camera.x = e.clientX - panStart.x;
    camera.y = e.clientY - panStart.y;
    _applyCameraTransform();
  });
  window.addEventListener("mouseup", () => {
    if (!mounted) return;
    isPanning = false;
    svg.classList.remove("panning");
  });

  // ------------------------------------------------------------------
  // Рендер
  // ------------------------------------------------------------------
  function rerender() {
    FF.graph.render(graphState, { blocksLayer, connectorsLayer }, { selectedBlockId });
    _wireBlockInteractions();
    _renderValidationPanel();
    _renderInspector();
  }

  function _renderValidationPanel() {
    const panel = document.getElementById("validation-panel");
    const host = document.getElementById("validation-list");
    host.innerHTML = "";
    if (!validation.issues || validation.issues.length === 0) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "block";
    validation.issues.forEach((issue) => {
      const item = document.createElement("div");
      item.className = "validation-item warning";
      item.textContent = "⚠️ " + FF.t("graph." + issue.code, issue.params);
      item.addEventListener("click", () => _selectBlock(issue.block_id));
      host.appendChild(item);
    });
  }

  function _selectBlock(blockId) {
    selectedBlockId = blockId;
    rerender();
  }

  function _renderInspector() {
    const panel = document.getElementById("validation-panel");
    // Инспектор делит правую панель со списком проверки — показываем то,
    // что сейчас важнее: выбранный блок, если он есть, иначе валидацию.
    if (!selectedBlockId) return;

    const block = graphState.blocks.find((b) => b.id === selectedBlockId);
    if (!block) return;

    panel.style.display = "block";
    const host = document.getElementById("validation-list");
    host.innerHTML = "";

    const canEditNow = canEdit || suggestModeOn;

    const titleInput = document.createElement("input");
    titleInput.value = block.title;
    titleInput.disabled = !canEditNow;
    titleInput.style.marginBottom = "8px";
    titleInput.addEventListener("change", () => patchNode([{ op: "edit_block", id: block.id, title: titleInput.value }]));
    host.appendChild(titleInput);

    const shapeRow = document.createElement("div");
    shapeRow.className = "flex gap-2";
    shapeRow.style.marginBottom = "8px";
    FF.graph.SHAPES.forEach((shape) => {
      const btn = document.createElement("button");
      btn.className = "btn btn-sm " + (block.shape === shape ? "btn-primary" : "btn-ghost");
      btn.textContent = shape.slice(0, 1).toUpperCase();
      btn.title = shape;
      btn.disabled = !canEditNow;
      btn.addEventListener("click", () => patchNode([{ op: "edit_block", id: block.id, shape }]));
      shapeRow.appendChild(btn);
    });
    host.appendChild(shapeRow);

    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.value = block.color;
    colorInput.disabled = !canEditNow;
    colorInput.style.width = "100%";
    colorInput.style.marginBottom = "8px";
    colorInput.addEventListener("input", () => patchNode([{ op: "edit_block", id: block.id, color: colorInput.value }]));
    host.appendChild(colorInput);

    if (canEditNow) {
      const addPointBtn = document.createElement("button");
      addPointBtn.className = "btn btn-ghost btn-sm";
      addPointBtn.style.width = "100%";
      addPointBtn.style.marginBottom = "8px";
      addPointBtn.textContent = FF.t("ui.inspector.add_port");
      addPointBtn.addEventListener("click", () =>
        patchNode([{ op: "add_point", block_id: block.id, rel_x: 0.5, rel_y: 1 }])
      );
      host.appendChild(addPointBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn btn-danger btn-sm";
      deleteBtn.style.width = "100%";
      deleteBtn.textContent = FF.t("ui.common.delete");
      deleteBtn.addEventListener("click", () => {
        patchNode([{ op: "delete_block", id: block.id }]);
        _selectBlock(null);
      });
      host.appendChild(deleteBtn);
    }
  }

  // ------------------------------------------------------------------
  // Добавление блока — панель тулбара внизу холста
  // ------------------------------------------------------------------
  function _wireToolbar(container) {
    container.querySelector("#btn-add-block").addEventListener("click", () => {
      const world = _screenToWorld(svg.clientWidth / 2, svg.clientHeight / 2);
      patchNode([{
        op: "add_block", title: "", shape: "rounded", color: "#9333ea",
        x: world.x - 80, y: world.y - 40, width: 160, height: 80,
        points: [{ rel_x: 0.5, rel_y: 1 }],
      }]);
    });

    const suggestBtn = container.querySelector("#btn-suggest-mode");
    if (!canEdit) {
      suggestBtn.style.display = "inline-flex";
      suggestBtn.addEventListener("click", () => {
        if (suggestModeOn && pendingOps.length > 0) {
          FF.panel.openSuggestionModal(pendingOps, nodeId);
        } else {
          _toggleSuggestMode(suggestBtn);
        }
      });
    }
  }

  function _toggleSuggestMode(btn) {
    suggestModeOn = !suggestModeOn;
    pendingOps = [];
    btn.classList.toggle("btn-primary", suggestModeOn);
    btn.classList.toggle("btn-ghost", !suggestModeOn);
    if (!suggestModeOn) {
      FF.api.get(`/api/nodes/${nodeId}`).then((node) => { graphState = node.diagram; rerender(); });
    }
  }

  // ------------------------------------------------------------------
  // Drag блока + рисование связи от точки к точке
  // ------------------------------------------------------------------
  let draggingBlock = null, dragOffset = null;
  let drawingFrom = null; // {pointId, blockId, x, y}

  function _wireBlockInteractions() {
    blocksLayer.querySelectorAll(".free-block-group").forEach((g) => {
      const blockId = g.getAttribute("data-block-id");

      g.querySelector(".free-block-shape").addEventListener("mousedown", (e) => {
        e.stopPropagation();
        _selectBlock(blockId);
        if (!canEdit && !suggestModeOn) return;
        const block = graphState.blocks.find((b) => b.id === blockId);
        const world = _screenToWorld(e.clientX, e.clientY);
        draggingBlock = blockId;
        dragOffset = { dx: world.x - block.x, dy: world.y - block.y };
      });

      g.querySelectorAll(".connection-point").forEach((circle) => {
        circle.addEventListener("mousedown", (e) => {
          e.stopPropagation();
          if (!canEdit && !suggestModeOn) return;
          const pointId = circle.getAttribute("data-point-id");
          const world = _screenToWorld(e.clientX, e.clientY);
          drawingFrom = { pointId, blockId, x: world.x, y: world.y };
          _highlightOtherBlocksPoints(blockId);
        });
        circle.addEventListener("mouseup", (e) => {
          e.stopPropagation();
          if (!drawingFrom) return;
          _finishConnector(circle.getAttribute("data-point-id"), circle.getAttribute("data-block-id"));
        });
      });
    });
  }

  /**
   * Подсвечивает точки на ЛЮБОМ другом блоке — свободная модель не имеет
   * правил "что с чем можно соединять по смыслу" (см. graph_validator.py):
   * единственное реальное ограничение — не соединять блок сам с собой,
   * это и отражает подсветка.
   */
  function _highlightOtherBlocksPoints(excludeBlockId) {
    blocksLayer.querySelectorAll(".connection-point").forEach((circle) => {
      if (circle.getAttribute("data-block-id") !== excludeBlockId) {
        circle.classList.add("compatible-target");
      }
    });
  }
  function _clearHighlight() {
    blocksLayer.querySelectorAll(".connection-point.compatible-target").forEach((c) => c.classList.remove("compatible-target"));
  }

  window.addEventListener("mousemove", (e) => {
    if (!mounted) return;
    if (draggingBlock) {
      const world = _screenToWorld(e.clientX, e.clientY);
      const block = graphState.blocks.find((b) => b.id === draggingBlock);
      block.x = world.x - dragOffset.dx;
      block.y = world.y - dragOffset.dy;
      FF.graph.render(graphState, { blocksLayer, connectorsLayer }, { selectedBlockId });
      _wireBlockInteractions();
      if (!suggestModeOn) FF.socket.moveBlock(nodeId, block.id, block.x, block.y, false);
    }
    if (drawingFrom) {
      _drawPreview(drawingFrom, _screenToWorld(e.clientX, e.clientY));
    }
    if (canEdit && !suggestModeOn) {
      const world = _screenToWorld(e.clientX, e.clientY);
      FF.socket.moveCursor(nodeId, world.x, world.y);
    }
  });

  let previewPath = null;
  function _drawPreview(from, to) {
    if (!previewPath) {
      previewPath = FF.graph.svgEl("path", { class: "connector-preview" });
      connectorsLayer.appendChild(previewPath);
    }
    previewPath.setAttribute("d", FF.graph.connectorPath(from, to));
  }
  function _clearPreview() {
    if (previewPath) { previewPath.remove(); previewPath = null; }
  }

  window.addEventListener("mouseup", () => {
    if (!mounted) return;
    if (draggingBlock) {
      const block = graphState.blocks.find((b) => b.id === draggingBlock);
      if (suggestModeOn) {
        pendingOps.push({ op: "edit_block", id: block.id, x: block.x, y: block.y });
      } else {
        FF.socket.moveBlock(nodeId, block.id, block.x, block.y, true);
      }
      draggingBlock = null;
    }
    if (drawingFrom) {
      drawingFrom = null;
      _clearPreview();
      _clearHighlight();
    }
  });

  function _finishConnector(toPointId, toBlockId) {
    const from = drawingFrom;
    drawingFrom = null;
    _clearPreview();
    _clearHighlight();
    if (!from || from.blockId === toBlockId) return;
    patchNode([{
      op: "add_connector", from_block: from.blockId, to_block: toBlockId,
      from_point: from.pointId, to_point: toPointId, arrow: true,
    }]);
  }

  // Клик по связи — удаление (только когда можно редактировать сразу; в
  // suggest-режиме предложить удаление связи можно через её id в pendingOps)
  function _wireConnectorClicks() {
    connectorsLayer.addEventListener("click", (e) => {
      const id = e.target.getAttribute && e.target.getAttribute("data-connector-id");
      if (!id || id.startsWith("pending-")) return;
      if (canEdit || suggestModeOn) {
        patchNode([{ op: "delete_connector", id }]);
      }
    });
  }

  // ------------------------------------------------------------------
  // Presence
  // ------------------------------------------------------------------
  const cursorElements = {};

  function _renderCursor(userId, x, y) {
    if (!cursorElements[userId]) {
      const g = FF.graph.svgEl("g");
      g.appendChild(FF.graph.svgEl("circle", { r: 5, fill: "var(--accent-secondary)" }));
      cursorsLayer.appendChild(g);
      cursorElements[userId] = g;
    }
    cursorElements[userId].setAttribute("transform", `translate(${x}, ${y})`);
  }
  function _removeCursor(userId) {
    if (cursorElements[userId]) { cursorElements[userId].remove(); delete cursorElements[userId]; }
  }

  function _makePresenceAvatar(user) {
    const el = document.createElement("div");
    el.className = "presence-avatar";
    el.title = user.display_name || user.username || "";
    el.setAttribute("data-user-id", user.id || "");
    el.textContent = (user.display_name || user.username || "?").slice(0, 1).toUpperCase();
    return el;
  }

  function _wireSocket() {
    FF.socket.on("diagram_state", (data) => {
      graphState = data.graph;
      validation = data.validation;
      const stack = document.getElementById("presence-stack");
      stack.innerHTML = "";
      (data.online || []).forEach((u) => stack.appendChild(_makePresenceAvatar(u)));
      rerender();
    });

    FF.socket.on("block_moved", (data) => {
      const block = graphState.blocks.find((b) => b.id === data.block_id);
      if (block) { block.x = data.x; block.y = data.y; rerender(); }
    });

    FF.socket.on("cursor_moved", (data) => _renderCursor(data.user_id, data.x, data.y));

    FF.socket.on("presence_left", (data) => {
      _removeCursor(data.user_id);
      const el = document.getElementById("presence-stack").querySelector(`[data-user-id="${data.user_id}"]`);
      if (el) el.remove();
    });

    FF.socket.on("presence_joined", (user) => {
      document.getElementById("presence-stack").appendChild(_makePresenceAvatar(user));
    });

    FF.socket.on("server_error", (data) => console.error("Canvas socket error:", data.message));
  }

  return { mount, unmount, currentValidation, patchNode: (ops) => patchNode(ops) };
})();
