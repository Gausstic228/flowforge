/**
 * FlowForge — create-node.js
 * Модалка создания узла вместо prompt(): название + карточки типа
 * (страница/холст). Возвращает Promise<{title, kind} | null> — сама по
 * себе HTTP-запросов не делает, созданием узла владеет tree-nav.js.
 */
window.FF = window.FF || {};

window.FF.createNode = (function () {
  "use strict";

  let selectedKind = "page";
  let resolver = null;

  function _select(kind) {
    selectedKind = kind;
    document.querySelectorAll("#create-node-modal .node-type-card").forEach((c) =>
      c.classList.toggle("selected", c.dataset.kind === kind));
  }

  function open(parentId, preferredKind) {
    const modal = document.getElementById("create-node-modal");
    if (!modal) return Promise.resolve(null);
    modal.style.display = "flex";
    document.getElementById("create-node-title").value = "";
    _select(preferredKind === "canvas" ? "canvas" : "page");
    setTimeout(() => document.getElementById("create-node-title").focus(), 50);

    return new Promise((resolve) => {
      resolver = (result) => {
        resolver = null;
        modal.style.display = "none";
        resolve(result);
      };
    });
  }

  function _submit() {
    const title = document.getElementById("create-node-title").value.trim();
    if (!title) {
      document.getElementById("create-node-title").focus();
      return;
    }
    if (resolver) resolver({ title: title, kind: selectedKind });
  }

  function init() {
    const modal = document.getElementById("create-node-modal");
    if (!modal) return;
    document.querySelectorAll("#create-node-modal .node-type-card").forEach((card) =>
      card.addEventListener("click", () => _select(card.dataset.kind)));
    document.getElementById("btn-cancel-create-node").addEventListener("click", () => {
      if (resolver) resolver(null);
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal && resolver) resolver(null);
    });
    document.getElementById("btn-submit-create-node").addEventListener("click", _submit);
    document.getElementById("create-node-title").addEventListener("keydown", (e) => {
      if (e.key === "Enter") _submit();
    });
  }

  document.addEventListener("DOMContentLoaded", init);
  return { open };
})();
