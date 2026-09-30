/**
 * FlowForge — canvas-graph.js
 *
 * Чистый слой отрисовки свободной диаграммы: превращает состояние графа
 * (FreeformDiagram.to_graph_dict()) в SVG. Форму, цвет, подпись блока и
 * позицию точек соединения выбирает человек — этот файл их не оценивает
 * и не навязывает какую-то "правильную" геометрию, только рисует то, что
 * есть в данных. Единственное, что здесь жёстко задано программой, —
 * САМА ГЕОМЕТРИЯ каждой доступной формы (как нарисовать прямоугольник vs
 * ромб), а не то, какую форму выбрать.
 *
 * Ничего не знает про WebSocket, drag или клики — только "дано состояние
 * графа, нарисуй его". Так один и тот же рендер работает и для живых
 * WebSocket-обновлений, и для статичного JSON (например, предпросмотр
 * Suggestion.patch до принятия).
 */
window.FF = window.FF || {};

window.FF.graph = (function () {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      for (const key in attrs) {
        el.setAttribute(key, attrs[key]);
      }
    }
    return el;
  }

  // -------------------------------------------------------------------
  // Геометрия форм: block -> SVG-элемент фигуры (без обводки/заливки —
  // цвет накладывается отдельно через block.color при отрисовке).
  // Каждая функция получает {x, y, width, height} и решает, как ей
  // нарисовать именно эту фигуру внутри этого прямоугольника габаритов.
  // -------------------------------------------------------------------
  const SHAPE_RENDERERS = {
    rectangle(b) {
      return svgEl("rect", { x: b.x, y: b.y, width: b.width, height: b.height });
    },
    rounded(b) {
      return svgEl("rect", {
        x: b.x, y: b.y, width: b.width, height: b.height,
        rx: Math.min(16, b.width / 6, b.height / 6),
      });
    },
    ellipse(b) {
      return svgEl("ellipse", {
        cx: b.x + b.width / 2, cy: b.y + b.height / 2,
        rx: b.width / 2, ry: b.height / 2,
      });
    },
    diamond(b) {
      const points = [
        [b.x + b.width / 2, b.y],
        [b.x + b.width, b.y + b.height / 2],
        [b.x + b.width / 2, b.y + b.height],
        [b.x, b.y + b.height / 2],
      ];
      return svgEl("polygon", { points: points.map((p) => p.join(",")).join(" ") });
    },
    hexagon(b) {
      const cut = Math.min(b.width * 0.2, 30);
      const points = [
        [b.x + cut, b.y], [b.x + b.width - cut, b.y],
        [b.x + b.width, b.y + b.height / 2],
        [b.x + b.width - cut, b.y + b.height], [b.x + cut, b.y + b.height],
        [b.x, b.y + b.height / 2],
      ];
      return svgEl("polygon", { points: points.map((p) => p.join(",")).join(" ") });
    },
    parallelogram(b) {
      const skew = Math.min(b.width * 0.15, 24);
      const points = [
        [b.x + skew, b.y], [b.x + b.width, b.y],
        [b.x + b.width - skew, b.y + b.height], [b.x, b.y + b.height],
      ];
      return svgEl("polygon", { points: points.map((p) => p.join(",")).join(" ") });
    },
  };

  function _renderShape(block) {
    const renderer = SHAPE_RENDERERS[block.shape] || SHAPE_RENDERERS.rounded;
    return renderer(block);
  }

  // -------------------------------------------------------------------
  // Точки соединения: rel_x/rel_y (0..1) -> абсолютные координаты на
  // холсте. Доля, а не пиксели, — точка остаётся на своём месте фигуры
  // при переносе или изменении размера блока, где бы её ни поставили.
  // -------------------------------------------------------------------
  function pointAbsolutePosition(block, point) {
    return {
      x: block.x + block.width * point.rel_x,
      y: block.y + block.height * point.rel_y,
    };
  }

  /** Индекс point_id -> {x, y, blockId} по всем блокам — нужен при отрисовке connector'ов. */
  function buildPointIndex(blocks) {
    const index = {};
    blocks.forEach((block) => {
      block.points.forEach((point) => {
        index[point.id] = { ...pointAbsolutePosition(block, point), blockId: block.id };
      });
    });
    return index;
  }

  /** Центр блока — используется, когда connector не привязан к конкретной точке. */
  function blockCenter(block) {
    return { x: block.x + block.width / 2, y: block.y + block.height / 2 };
  }

  function _blockById(blocks, id) {
    return blocks.find((b) => b.id === id);
  }

  function renderBlock(block, options) {
    const g = svgEl("g", { "data-block-id": block.id, class: "free-block-group" });

    const shape = _renderShape(block);
    const classes = ["free-block-shape"];
    if (options.selectedBlockId === block.id) classes.push("selected");
    shape.setAttribute("class", classes.join(" "));
    shape.setAttribute("fill", block.color);
    shape.setAttribute("stroke", block.color);
    shape.setAttribute("fill-opacity", "0.18");
    g.appendChild(shape);

    if (block.title) {
      const title = svgEl("text", {
        x: block.x + block.width / 2, y: block.y + block.height / 2,
        "text-anchor": "middle", "dominant-baseline": "middle",
        class: "free-block-title", fill: block.color,
      });
      title.textContent = block.title;
      g.appendChild(title);
    }

    block.points.forEach((point) => {
      const pos = pointAbsolutePosition(block, point);
      const isCompatible = options.compatiblePointIds && options.compatiblePointIds.has(point.id);
      const circle = svgEl("circle", {
        cx: pos.x, cy: pos.y, r: 5,
        class: "connection-point" + (isCompatible ? " compatible-target" : ""),
        "data-point-id": point.id,
        "data-block-id": block.id,
      });
      g.appendChild(circle);
    });

    return g;
  }

  /**
   * Кривая Безье между двумя точками — горизонтальные "ручки" дают
   * привычный вид растекающихся линий (Node-RED/Blueprint-стиль), а не
   * прямые углы, которые визуально спорят со свободным расположением
   * фигур (в отличие от строгой лесенки IDEF0, здесь блоки не выстроены
   * по диагонали, так что прямые линии смотрелись бы хаотичнее).
   */
  function connectorPath(from, to) {
    const dx = Math.max(Math.abs(to.x - from.x) * 0.5, 40);
    return `M ${from.x},${from.y} C ${from.x + dx},${from.y} ${to.x - dx},${to.y} ${to.x},${to.y}`;
  }

  function renderConnector(connector, blocks, pointIndex) {
    const fromBlock = _blockById(blocks, connector.from_block);
    const toBlock = _blockById(blocks, connector.to_block);
    if (!fromBlock || !toBlock) return null;

    const from = connector.from_point ? pointIndex[connector.from_point] : blockCenter(fromBlock);
    const to = connector.to_point ? pointIndex[connector.to_point] : blockCenter(toBlock);
    if (!from || !to) return null;

    const g = svgEl("g", { "data-connector-id": connector.id });

    const path = svgEl("path", {
      d: connectorPath(from, to),
      class: "connector-line" + (connector.dashed ? " dashed" : ""),
      stroke: connector.color,
      "data-connector-id": connector.id,
    });
    if (connector.arrow) {
      path.setAttribute("marker-end", "url(#arrowhead-" + connector.id + ")");
    }
    g.appendChild(path);

    if (connector.arrow) {
      // Отдельный marker на связь (а не один общий #arrowhead), потому что
      // у каждой связи свой цвет стрелки — общий marker не смог бы
      // наследовать per-connector цвет через CSS-переменную надёжно во
      // всех браузерах, тогда как отдельный marker с фиксированным fill
      // работает всегда одинаково.
      const marker = svgEl("marker", {
        id: "arrowhead-" + connector.id, markerWidth: 10, markerHeight: 8,
        refX: 9, refY: 4, orient: "auto",
      });
      marker.appendChild(svgEl("path", { d: "M0,0 L10,4 L0,8 Z", fill: connector.color }));
      g.appendChild(marker);
    }

    if (connector.label) {
      const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
      const label = svgEl("text", {
        x: mid.x, y: mid.y - 6, "text-anchor": "middle", class: "connector-label",
      });
      label.textContent = connector.label;
      g.appendChild(label);
    }

    return g;
  }

  /**
   * Полная перерисовка графа. options:
   *   selectedBlockId    — id блока, который сейчас выделен
   *   compatiblePointIds — Set id точек, подсвечиваемых при рисовании связи
   */
  function render(graphState, layers, options) {
    options = options || {};
    layers.blocksLayer.innerHTML = "";
    layers.connectorsLayer.innerHTML = "";

    const pointIndex = buildPointIndex(graphState.blocks);

    graphState.connectors.forEach((connector) => {
      const el = renderConnector(connector, graphState.blocks, pointIndex);
      if (el) layers.connectorsLayer.appendChild(el);
    });

    // Блоки рисуются по z_index, чтобы верхние по слою фигуры физически
    // оказались позже в DOM — иначе наложение выглядело бы случайным.
    [...graphState.blocks]
      .sort((a, b) => a.z_index - b.z_index)
      .forEach((block) => layers.blocksLayer.appendChild(renderBlock(block, options)));
  }

  return {
    render,
    pointAbsolutePosition,
    buildPointIndex,
    blockCenter,
    connectorPath,
    svgEl,
    SHAPES: Object.keys(SHAPE_RENDERERS),
  };
})();
