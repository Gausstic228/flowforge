/**
 * FlowForge — canvas-tools.js
 * Док инструментов в духе UML/CASE (Ramus/PlantUML):
 *  — «Выбор»: стандартное поведение;
 *  — «Панорама»: перетаскивание холста, включая за блоки;
 *  — «Связь»: точки-порты блоков видны постоянно, тянешь от порта к порту;
 *  — «Фигуры»: выбрал фигуру → клики по холсту ставят блоки этой фигуры
 *    (удерживается до Esc или возврата в «Выбор»);
 *  — «Удалить»: убрать выбранный блок (также работает клавиша Delete);
 *  — зум ＋/－/⛶.
 */
window.FF = window.FF || {};

window.FF.canvasTools = (function () {
  "use strict";

  let selectedShape = "rounded";
  let currentContainer = null;
  window.FF_SELECTED_SHAPE = selectedShape;

  function _hint(text) {
    const el = currentContainer && currentContainer.querySelector("#canvas-hint");
    if (el) el.textContent = text || "";
  }

  function _setActive(dock, id) {
    dock.querySelectorAll(".tool-btn").forEach((b) => b.classList.remove("active"));
    const btn = id && dock.querySelector("#" + id);
    if (btn) btn.classList.add("active");
  }

  function wire(container, canEdit) {
    currentContainer = container;
    const dock = container.querySelector("#tool-dock");
    if (!dock) return;
    dock.style.display = canEdit ? "flex" : "none";
    const shapeMenu = container.querySelector("#shape-menu");

    // --- Палитра фигур: выбор = режим создания, Esc — выход ---
    container.querySelectorAll(".shape-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.shape === selectedShape);
      btn.addEventListener("click", () => {
        selectedShape = btn.dataset.shape;
        window.FF_SELECTED_SHAPE = selectedShape;
        container.querySelectorAll(".shape-item").forEach((b) =>
          b.classList.toggle("active", b === btn));
        shapeMenu.classList.remove("open");
        _setActive(dock, "tool-shapes");
        FF.canvas.setToolMode("create");
        _hint(FF.t("ui.canvas.hint_create") + " · Esc");
      });
    });
    container.querySelector("#tool-shapes").addEventListener("click", (e) => {
      e.stopPropagation();
      shapeMenu.classList.toggle("open");
    });
    shapeMenu.addEventListener("click", (e) => e.stopPropagation());

    // --- Режимы ---
    container.querySelector("#tool-select").addEventListener("click", () => {
      shapeMenu.classList.remove("open");
      _setActive(dock, "tool-select");
      FF.canvas.setToolMode("select");
      _hint("");
    });
    container.querySelector("#tool-pan").addEventListener("click", () => {
      shapeMenu.classList.remove("open");
      _setActive(dock, "tool-pan");
      FF.canvas.setToolMode("pan");
      _hint(FF.t("ui.canvas.hint_pan"));
    });
    container.querySelector("#tool-connect").addEventListener("click", () => {
      shapeMenu.classList.remove("open");
      _setActive(dock, "tool-connect");
      FF.canvas.setToolMode("connect");
      _hint(FF.t("ui.canvas.hint_connect"));
    });
    container.querySelector("#tool-delete").addEventListener("click", () => {
      FF.canvas.deleteSelected();
    });
    container.querySelector("#tool-zoom-in").addEventListener("click", () => FF.canvas.zoomBy(1.25));
    container.querySelector("#tool-zoom-out").addEventListener("click", () => FF.canvas.zoomBy(1 / 1.25));
    container.querySelector("#tool-zoom-fit").addEventListener("click", () => FF.canvas.zoomFit());

    // Esc из любого места — назад в «Выбор»
    container.ownerDocument.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        shapeMenu.classList.remove("open");
        _setActive(dock, "tool-select");
        FF.canvas.setToolMode("select");
        _hint("");
      }
    });
  }

  // canvas.js зовёт при смене режима (например, при unmount) — синхронизируем подсветку
  function onModeChange(mode) {
    const dock = currentContainer && currentContainer.querySelector("#tool-dock");
    if (!dock) return;
    const map = { select: "tool-select", pan: "tool-pan", connect: "tool-connect", create: "tool-shapes" };
    _setActive(dock, map[mode] || null);
    if (mode === "select") _hint("");
    if (mode === "pan") _hint(FF.t("ui.canvas.hint_pan"));
    if (mode === "connect") _hint(FF.t("ui.canvas.hint_connect"));
    if (mode === "create") _hint(FF.t("ui.canvas.hint_create") + " · Esc");
  }

  return { wire, onModeChange };
})();
