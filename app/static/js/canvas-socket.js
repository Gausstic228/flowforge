/**
 * FlowForge — canvas-socket.js
 *
 * Обёртка над Socket.IO-клиентом. Реализует ровно тот протокол событий,
 * который сервер объявляет в app/services/realtime.py:
 *   клиент шлёт: join_diagram, presence_ping, cursor_moved, block_moved(final?)
 *   сервер шлёт: diagram_state, presence_joined/left, cursor_moved,
 *                block_moved, server_error, suggestions_changed
 *
 * Структура диаграммы (блоки, точки, связи) НЕ меняется через сокет вообще —
 * это HTTP-эндпоинт POST /api/nodes/<id>/patch (см. editor.js), после
 * которого сервер рассылает итоговый diagram_state той же комнате. Сокет
 * несёт только то, что имеет смысл терять при переподключении: позицию
 * при перетаскивании, курсоры, presence.
 *
 * Этот файл не трогает DOM и не знает про рендеринг — только шлёт/принимает
 * события через простой подписочный интерфейс (.on(event, handler)).
 */
window.FF = window.FF || {};

window.FF.socket = (function () {
  "use strict";

  const PRESENCE_PING_INTERVAL_MS = 20_000; // держим маржу к PRESENCE_TTL=45с на backend

  let io_socket = null;
  let pingTimer = null;
  const listeners = {};

  function emitLocal(event, payload) {
    (listeners[event] || []).forEach((fn) => fn(payload));
  }

  function connect(nodeId) {
    io_socket = window.io({ transports: ["websocket", "polling"] });

    io_socket.on("connect", () => {
      io_socket.emit("join_diagram", { node_id: nodeId });
      clearInterval(pingTimer);
      pingTimer = setInterval(() => send("presence_ping"), PRESENCE_PING_INTERVAL_MS);
      emitLocal("connected", null);
    });

    // Прокидываем все события сервера один в один — editor.js/canvas.js
    // решают, что с ними делать; этот файл ничего не интерпретирует сам.
    ["diagram_state", "presence_joined", "presence_left", "cursor_moved", "block_moved", "server_error"].forEach(
      (event) => io_socket.on(event, (payload) => emitLocal(event, payload))
    );

    io_socket.on("disconnect", () => {
      clearInterval(pingTimer);
      emitLocal("disconnected", null);
    });
  }

  function disconnect() {
    clearInterval(pingTimer);
    if (io_socket) {
      io_socket.disconnect();
      io_socket = null;
    }
  }

  function on(event, handler) {
    listeners[event] = listeners[event] || [];
    listeners[event].push(handler);
  }

  function send(event, payload) {
    if (io_socket && io_socket.connected) {
      io_socket.emit(event, payload || {});
    }
  }

  return {
    connect,
    disconnect,
    on,
    send,
    // Удобные обёртки над send() — вызывающему коду не нужно самому
    // собирать сырые объекты payload с именами полей backend'а.
    moveCursor: (nodeId, x, y) => send("cursor_moved", { node_id: nodeId, x, y }),
    moveBlock: (nodeId, blockId, x, y, final) =>
      send("block_moved", { node_id: nodeId, block_id: blockId, x, y, final: !!final }),
  };
})();
