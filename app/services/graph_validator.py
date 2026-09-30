"""
graph_validator — движок операций над свободной диаграммой FlowForge.

В отличие от более ранней версии продукта здесь НЕТ типизированных портов и
никакой проверки "что с чем можно соединять по смыслу": форму, цвет, подписи
блока и точки соединения выбирает человек, программа их не оценивает.
Единственное, что здесь проверяется, — структурная целостность:
  - связь не может указывать на несуществующий блок/точку;
  - точка удаляется только вместе со связями, которые к ней подключены
    (иначе в базе останется связь в никуда).

apply_patch() — единственный путь изменить диаграмму: им пользуются и прямое
редактирование (POST /patch), и принятие Suggestion, и «сухая» проверка
черновика (dry_run_patch) — поэтому применение везде одинаковое.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import or_

from app import db
from app.models._util import utcnow
from app.models.diagram import BlockShape, Connector, ConnectionPoint, FreeformBlock, FreeformDiagram
from app.services.i18n import t

logger = logging.getLogger(__name__)

MAX_PATCH_OPS = 200
MAX_TITLE_LEN = 300
MAX_LABEL_LEN = 200
_COORD_LIMIT = 100_000.0
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class GraphError(Exception):
    """Ожидаемая ошибка: текст уже переведён и предназначен пользователю."""


# ---------------------------------------------------------------------------
# Мелкие помощники
# ---------------------------------------------------------------------------
def _short(value) -> str:
    return str(value)[:40]


def _clean_text(value, limit: int) -> str:
    return ("" if value is None else str(value)).strip()[:limit]


def _clean_color(value, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    return text if _HEX_COLOR_RE.match(text) else fallback


def parse_coordinate(value) -> float:
    """Число из клиентских данных; ValueError/TypeError при мусоре, NaN и бесконечности."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("coordinate is not finite")
    return max(-_COORD_LIMIT, min(_COORD_LIMIT, number))


def _clean_fraction(value, fallback: float) -> float:
    """0..1 — доля ширины/высоты блока (позиция точки на фигуре)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return max(0.0, min(1.0, number))


def _claim_id(candidate, model) -> str:
    """
    Клиент может сам назначить id новым сущностям (32 hex), чтобы один патч
    мог создать блок и сразу его соединить. Сервер проверяет формат и
    занятость; без id выдаёт свой.
    """
    if candidate is None:
        return uuid.uuid4().hex
    if not isinstance(candidate, str) or not _ID_RE.match(candidate):
        raise GraphError(t("graph.invalid_id", id=_short(candidate)))
    if db.session.get(model, candidate) is not None:
        raise GraphError(t("graph.id_taken", id=candidate))
    return candidate


def _get_block(diagram: FreeformDiagram, block_id) -> FreeformBlock:
    block = db.session.get(FreeformBlock, block_id) if isinstance(block_id, str) else None
    if block is None or block.diagram_id != diagram.id:
        raise GraphError(t("graph.block_not_found_in_diagram", id=_short(block_id)))
    return block


def _get_point(diagram: FreeformDiagram, point_id):
    """None — допустимо (связь без привязки к конкретной точке); иначе точка должна существовать."""
    if point_id is None:
        return None
    point = db.session.get(ConnectionPoint, point_id) if isinstance(point_id, str) else None
    block = db.session.get(FreeformBlock, point.block_id) if point is not None else None
    if block is None or block.diagram_id != diagram.id:
        raise GraphError(t("graph.point_not_found_in_diagram", id=_short(point_id)))
    return point


def _delete_connectors_touching_block(diagram: FreeformDiagram, block_id: str) -> None:
    db.session.query(Connector).filter(
        Connector.diagram_id == diagram.id,
        or_(Connector.from_block_id == block_id, Connector.to_block_id == block_id),
    ).delete(synchronize_session="fetch")


def _detach_connectors_from_point(diagram: FreeformDiagram, point_id: str) -> None:
    """Точка удаляется — связи, которые за неё держались, остаются, но становятся «от блока вообще»."""
    db.session.query(Connector).filter(
        Connector.diagram_id == diagram.id, Connector.from_point_id == point_id
    ).update({"from_point_id": None}, synchronize_session="fetch")
    db.session.query(Connector).filter(
        Connector.diagram_id == diagram.id, Connector.to_point_id == point_id
    ).update({"to_point_id": None}, synchronize_session="fetch")


# ---------------------------------------------------------------------------
# Сводка по диаграмме. Структурная, не смысловая: блок без единой связи —
# предупреждение (может быть и нормально — не всё обязано быть соединено),
# ошибок в свободной модели не бывает вовсе, потому что нет правил "что
# правильно" — есть только то, что человек нарисовал.
# ---------------------------------------------------------------------------
@dataclass
class ValidationIssue:
    level: str          # только "warning" в этой модели — не осталось правил на "error"
    code: str
    block_id: str
    params: dict

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "block_id": self.block_id, "params": self.params}


def summarize(diagram: FreeformDiagram) -> dict:
    connected_block_ids = set()
    for connector in diagram.connectors:
        connected_block_ids.add(connector.from_block_id)
        connected_block_ids.add(connector.to_block_id)

    issues = [
        ValidationIssue("warning", "block_disconnected", block.id, {"title": block.title})
        for block in diagram.blocks
        if block.id not in connected_block_ids
    ]
    return {"ok": True, "issues": [issue.to_dict() for issue in issues]}


# ---------------------------------------------------------------------------
# Операции патча
# ---------------------------------------------------------------------------
def _parse_shape(value) -> BlockShape:
    try:
        return BlockShape(value)
    except ValueError:
        raise GraphError(t("graph.invalid_shape", shape=_short(value))) from None


def _add_point(block: FreeformBlock, spec: dict) -> ConnectionPoint:
    point = ConnectionPoint(
        id=_claim_id(spec.get("id"), ConnectionPoint),
        block_id=block.id,
        rel_x=_clean_fraction(spec.get("rel_x"), 0.5),
        rel_y=_clean_fraction(spec.get("rel_y"), 0.5),
        label=_clean_text(spec.get("label"), MAX_LABEL_LEN),
    )
    db.session.add(point)
    db.session.flush()
    return point


def _op_add_block(diagram: FreeformDiagram, step: dict) -> None:
    block = FreeformBlock(
        id=_claim_id(step.get("id"), FreeformBlock),
        diagram_id=diagram.id,
        title=_clean_text(step.get("title"), MAX_TITLE_LEN),
        shape=_parse_shape(step.get("shape", BlockShape.ROUNDED.value)),
        color=_clean_color(step.get("color"), "#9333ea"),
        pos_x=parse_coordinate(step.get("x", 0)),
        pos_y=parse_coordinate(step.get("y", 0)),
        width=max(20.0, parse_coordinate(step.get("width", 160))),
        height=max(20.0, parse_coordinate(step.get("height", 80))),
        z_index=int(step.get("z_index", 0)),
    )
    db.session.add(block)
    db.session.flush()
    for spec in step.get("points", []):
        _add_point(block, spec)


def _op_edit_block(diagram: FreeformDiagram, step: dict) -> None:
    block = _get_block(diagram, step["id"])
    if "title" in step:
        block.title = _clean_text(step["title"], MAX_TITLE_LEN)
    if "shape" in step:
        block.shape = _parse_shape(step["shape"])
    if "color" in step:
        block.color = _clean_color(step["color"], block.color)
    if "x" in step:
        block.pos_x = parse_coordinate(step["x"])
    if "y" in step:
        block.pos_y = parse_coordinate(step["y"])
    if "width" in step:
        block.width = max(20.0, parse_coordinate(step["width"]))
    if "height" in step:
        block.height = max(20.0, parse_coordinate(step["height"]))
    if "z_index" in step:
        block.z_index = int(step["z_index"])


def _op_delete_block(diagram: FreeformDiagram, step: dict) -> None:
    block = _get_block(diagram, step["id"])
    _delete_connectors_touching_block(diagram, block.id)
    db.session.delete(block)
    db.session.flush()


def _op_add_point(diagram: FreeformDiagram, step: dict) -> None:
    _add_point(_get_block(diagram, step["block_id"]), step)


def _op_edit_point(diagram: FreeformDiagram, step: dict) -> None:
    point = _get_point(diagram, step["id"])
    if point is None:
        raise GraphError(t("graph.point_not_found_in_diagram", id=_short(step.get("id"))))
    if "rel_x" in step:
        point.rel_x = _clean_fraction(step["rel_x"], point.rel_x)
    if "rel_y" in step:
        point.rel_y = _clean_fraction(step["rel_y"], point.rel_y)
    if "label" in step:
        point.label = _clean_text(step["label"], MAX_LABEL_LEN)


def _op_delete_point(diagram: FreeformDiagram, step: dict) -> None:
    point = _get_point(diagram, step["id"])
    if point is None:
        raise GraphError(t("graph.point_not_found_in_diagram", id=_short(step.get("id"))))
    _detach_connectors_from_point(diagram, point.id)
    db.session.delete(point)
    db.session.flush()


def _op_add_connector(diagram: FreeformDiagram, step: dict) -> None:
    from_block = _get_block(diagram, step["from_block"])
    to_block = _get_block(diagram, step["to_block"])
    from_point = _get_point(diagram, step.get("from_point"))
    to_point = _get_point(diagram, step.get("to_point"))
    if from_point is not None and from_point.block_id != from_block.id:
        raise GraphError(t("graph.point_wrong_block"))
    if to_point is not None and to_point.block_id != to_block.id:
        raise GraphError(t("graph.point_wrong_block"))

    connector = Connector(
        id=_claim_id(step.get("id"), Connector),
        diagram_id=diagram.id,
        from_block_id=from_block.id,
        to_block_id=to_block.id,
        from_point_id=from_point.id if from_point else None,
        to_point_id=to_point.id if to_point else None,
        label=_clean_text(step.get("label"), MAX_LABEL_LEN),
        color=_clean_color(step.get("color"), "#5c6178"),
        dashed=bool(step.get("dashed", False)),
        arrow=bool(step.get("arrow", True)),
    )
    db.session.add(connector)
    db.session.flush()


def _op_edit_connector(diagram: FreeformDiagram, step: dict) -> None:
    connector = db.session.get(Connector, step["id"]) if isinstance(step.get("id"), str) else None
    if connector is None or connector.diagram_id != diagram.id:
        raise GraphError(t("graph.connector_not_found_in_diagram", id=_short(step.get("id"))))
    if "label" in step:
        connector.label = _clean_text(step["label"], MAX_LABEL_LEN)
    if "color" in step:
        connector.color = _clean_color(step["color"], connector.color)
    if "dashed" in step:
        connector.dashed = bool(step["dashed"])
    if "arrow" in step:
        connector.arrow = bool(step["arrow"])


def _op_delete_connector(diagram: FreeformDiagram, step: dict) -> None:
    connector = db.session.get(Connector, step["id"]) if isinstance(step.get("id"), str) else None
    if connector is None or connector.diagram_id != diagram.id:
        raise GraphError(t("graph.connector_not_found_in_diagram", id=_short(step.get("id"))))
    db.session.delete(connector)
    db.session.flush()


_OPERATIONS = {
    "add_block": _op_add_block,
    "edit_block": _op_edit_block,
    "delete_block": _op_delete_block,
    "add_point": _op_add_point,
    "edit_point": _op_edit_point,
    "delete_point": _op_delete_point,
    "add_connector": _op_add_connector,
    "edit_connector": _op_edit_connector,
    "delete_connector": _op_delete_connector,
}


def apply_patch(diagram: FreeformDiagram, patch) -> None:
    """
    Применяет список операций к диаграмме (без commit). Формат:

      {"op": "add_block", "id"?, "title"?, "shape"?, "color"?, "x", "y",
       "width"?, "height"?, "points": [{"id"?, "rel_x"?, "rel_y"?, "label"?}]}
      {"op": "edit_block", "id", "title"?, "shape"?, "color"?, "x"?, "y"?, "width"?, "height"?}
      {"op": "delete_block", "id"}
      {"op": "add_point", "block_id", "id"?, "rel_x"?, "rel_y"?, "label"?}
      {"op": "edit_point", "id", "rel_x"?, "rel_y"?, "label"?}
      {"op": "delete_point", "id"}
      {"op": "add_connector", "id"?, "from_block", "to_block", "from_point"?,
       "to_point"?, "label"?, "color"?, "dashed"?, "arrow"?}
      {"op": "edit_connector", "id", "label"?, "color"?, "dashed"?, "arrow"?}
      {"op": "delete_connector", "id"}

    Любая ошибка — GraphError; вызывающий обязан откатить транзакцию
    (db.session.rollback()), тогда патч применяется «всё или ничего».
    """
    if not isinstance(patch, list) or not patch:
        raise GraphError(t("graph.patch_must_be_nonempty_list"))
    if len(patch) > MAX_PATCH_OPS:
        raise GraphError(t("graph.patch_too_large", limit=MAX_PATCH_OPS))

    for step in patch:
        operation = _OPERATIONS.get(step.get("op")) if isinstance(step, dict) else None
        if operation is None:
            name = step.get("op") if isinstance(step, dict) else step
            raise GraphError(t("graph.unknown_patch_op", op=_short(name)))
        try:
            operation(diagram, step)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.debug("malformed patch operation %r", step, exc_info=True)
            raise GraphError(t("graph.malformed_patch_op")) from exc

    diagram.version += 1
    diagram.node.project.updated_at = utcnow()  # проект «свежий» для каталога


def dry_run_patch(diagram: FreeformDiagram, patch) -> None:
    """Проверяет патч на SAVEPOINT'е и ВСЕГДА откатывает его — в базе не остаётся следа."""
    nested = db.session.begin_nested()
    try:
        apply_patch(diagram, patch)
    finally:
        nested.rollback()
