/**
 * FlowForge — canvas-tools.js
 * Док инструментов (выбор/пан/удаление/зум) и палитра фигур для канваса.
 * Форма нового блока читается canvas.js из window.FF_SELECTED_SHAPE.
 * Подключается самим canvas.js через FF.canvasTools.wire(container, canEdit).
 */
window.FF = window.FF || {};

window.FF.canvasTools = (function () {
  "use strict";

  let selectedShape = "rectangle";
  window.FF_SELECTED_SHAPE = selectedShape;

  function wire(container, canEdit) {
    const dock = container.querySelector("#tool-dock");
    if (!dock) return;
    dock.style.display = canEdit ? "flex" : "none";
    const shapeMenu = container.querySelector("#shape-menu");

    container.querySelectorAll(".shape-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.shape === selectedShape);
      btn.addEventListener("click", () => {
        selectedShape = btn.dataset.shape;
        window.FF_SELECTED_SHAPE = selectedShape;
        container.querySelectorAll(".shape-item").forEach((b) =>
          b.classList.toggle("active", b === btn));
        shapeMenu.classList.remove("open");
        container.querySelector("#btn-add-block").click();
      });
    });
    container.querySelector("#tool-shapes").addEventListener("click", (e) => {
      e.stopPropagation();
      shapeMenu.classList.toggle("open");
    });
    shapeMenu.addEventListener("click", (e) => e.stopPropagation());

    const modeBtn = (id, mode) => container.querySelector("#" + id).addEventListener("click", () => {
      dock.querySelectorAll(".tool-btn").forEach((b) => b.classList.remove("active"));
      container.querySelector("#" + id).classList.add("active");
      FF.canvas.setToolMode(mode);
    });
    modeBtn("tool-select", "select");
    modeBtn("tool-pan", "pan");

    container.querySelector("#tool-delete").addEventListener("click", () => FF.canvas.deleteSelected());
    container.querySelector("#tool-zoom-in").addEventListener("click", () => FF.canvas.zoomBy(1.25));
    container.querySelector("#tool-zoom-out").addEventListener("click", () => FF.canvas.zoomBy(1 / 1.25));
    container.querySelector("#tool-zoom-fit").addEventListener("click", () => FF.canvas.zoomFit());
  }

  return { wire };
})();
