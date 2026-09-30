"""
HTTP API дерева проекта: markdown-страницы и канвасы — узлы одного дерева
(app/models/node.py), а не два отдельных раздела.

Структура диаграммы меняется ТОЛЬКО через патч (см. graph_validator.apply_patch):
  POST /<id>/patch        — прямое редактирование канваса (owner / editor);
  POST /<id>/patch/check  — «сухая» проверка черновика, ничего не сохраняет.
Текст markdown-страницы меняется через PUT /<id>/content.
Положение узла в дереве (родитель, порядок среди братьев) — через PATCH /<id>/move.
"""
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models._util import utcnow
from app.models.node import Node, NodeKind
from app.models.diagram import FreeformBlock, FreeformDiagram
from app.models.suggestion import Suggestion
from app.services.graph_validator import GraphError, apply_patch, dry_run_patch
from app.services.i18n import t
from app.services.page_patch import MAX_CONTENT_LEN
from app.services.realtime import broadcast_diagram_state, diagram_payload

nodes_bp = Blueprint("nodes", __name__)

MAX_TITLE_LEN = 200


def _node_or_404(node_id: str) -> Node:
    node = db.session.get(Node, node_id)
    if node is None:
        abort(404, t("node.not_found"))
    return node


def _json_body() -> dict:
    data = request.get_json(silent=True, force=True)
    if data is None:
        abort(400, t("project.invalid_json_body"))
    return data


def _next_position(project_id: int, parent_id) -> int:
    last = (
        db.session.query(Node)
        .filter_by(project_id=project_id, parent_id=parent_id)
        .order_by(Node.position.desc())
        .first()
    )
    return (last.position + 1) if last else 0


@nodes_bp.route("/<node_id>", methods=["GET"])
def get_node(node_id):
    """Полная запись узла: markdown-текст для page, актуальный граф для canvas."""
    node = _node_or_404(node_id)
    viewer = current_user if current_user.is_authenticated else None
    if not node.project.can_view(viewer):
        abort(403, t("node.no_access"))
    return jsonify(node.public_dict_with_content())


@nodes_bp.route("", methods=["POST"])
@login_required
def create_node():
    """
    Новый узел под parent_id (титульный лист создаётся отдельно вместе с
    проектом — см. routes/projects.py, здесь всегда есть родитель).
    Без описания и прочих полей на старте — только тип и куда его положить;
    название человек допишет прямо в дереве или в самом узле.
    """
    data = _json_body()
    parent = _node_or_404(str(data.get("parent_id") or ""))
    if not parent.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))

    try:
        kind = NodeKind(data.get("kind"))
    except ValueError:
        abort(400, t("node.invalid_kind"))

    node = Node(
        project_id=parent.project_id,
        parent_id=parent.id,
        kind=kind,
        title=str(data.get("title") or "").strip()[:MAX_TITLE_LEN] or t(f"node.default_title_{kind.value}"),
        position=_next_position(parent.project_id, parent.id),
    )
    db.session.add(node)
    db.session.flush()
    if kind is NodeKind.CANVAS:
        db.session.add(FreeformDiagram(id=node.id))

    db.session.commit()
    return jsonify(node.public_dict_with_content()), 201


@nodes_bp.route("/<node_id>", methods=["PATCH"])
@login_required
def rename_node(node_id):
    node = _node_or_404(node_id)
    if not node.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))

    data = _json_body()
    title = str(data.get("title") or "").strip()[:MAX_TITLE_LEN]
    if not title:
        abort(400, t("node.title_required"))
    node.title = title
    db.session.commit()
    return jsonify(node.public_dict())


@nodes_bp.route("/<node_id>/move", methods=["PATCH"])
@login_required
def move_node(node_id):
    """Смена родителя и/или позиции — перетаскивание узла в дереве."""
    node = _node_or_404(node_id)
    if not node.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))
    if node.parent_id is None:
        abort(400, t("node.cannot_move_root"))

    data = _json_body()
    new_parent_id = data.get("parent_id", node.parent_id)
    new_parent = _node_or_404(new_parent_id) if new_parent_id else None
    if new_parent is None or new_parent.project_id != node.project_id:
        abort(400, t("node.invalid_parent"))
    if new_parent.kind is not NodeKind.PAGE:
        abort(400, t("node.parent_must_be_page"))
    if _is_descendant(node.id, new_parent.id):
        abort(400, t("node.cannot_move_into_own_subtree"))

    node.parent_id = new_parent.id
    node.position = int(data.get("position", _next_position(node.project_id, new_parent.id)))
    db.session.commit()
    return jsonify(node.public_dict())


def _is_descendant(ancestor_id: str, candidate_id: str) -> bool:
    """True, если candidate_id лежит внутри поддерева ancestor_id (включая сам ancestor_id)."""
    current = db.session.get(Node, candidate_id)
    while current is not None:
        if current.id == ancestor_id:
            return True
        current = db.session.get(Node, current.parent_id) if current.parent_id else None
    return False


@nodes_bp.route("/<node_id>", methods=["DELETE"])
@login_required
def delete_node(node_id):
    node = _node_or_404(node_id)
    if not node.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))
    if node.parent_id is None:
        abort(400, t("node.cannot_delete_root"))

    db.session.delete(node)  # cascade удаляет поддерево и диаграмму канваса
    db.session.commit()
    return "", 204


@nodes_bp.route("/<node_id>/content", methods=["PUT"])
@login_required
def update_content(node_id):
    """Сохранить markdown-текст страницы целиком (id-узел должен быть kind=page)."""
    node = _node_or_404(node_id)
    if not node.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))
    if node.kind is not NodeKind.PAGE:
        abort(400, t("node.not_a_page"))

    data = _json_body()
    content = str(data.get("content") or "")
    if len(content) > MAX_CONTENT_LEN:
        abort(400, t("node.content_too_large", limit=MAX_CONTENT_LEN))

    node.content = content
    node.updated_at = utcnow()
    db.session.commit()
    return jsonify(node.public_dict_with_content())


# ---------------------------------------------------------------------------
# Канвас: та же операционная модель, что была у /api/diagrams в предыдущей
# версии — просто теперь id узла и id диаграммы совпадают по построению.
# ---------------------------------------------------------------------------
def _canvas_or_400(node: Node) -> FreeformDiagram:
    if node.kind is not NodeKind.CANVAS or node.diagram is None:
        abort(400, t("node.not_a_canvas"))
    return node.diagram


def _patch_from_request():
    return (request.get_json(silent=True) or {}).get("patch")


@nodes_bp.route("/<node_id>/patch", methods=["POST"])
@login_required
def apply_canvas_patch(node_id):
    node = _node_or_404(node_id)
    if not node.project.can_edit(current_user):
        abort(403, t("node.no_edit_permission"))
    diagram = _canvas_or_400(node)

    try:
        apply_patch(diagram, _patch_from_request())
        db.session.commit()
    except GraphError as exc:
        db.session.rollback()
        abort(400, str(exc))

    payload = diagram_payload(diagram)
    broadcast_diagram_state(diagram, payload)
    return jsonify(payload)


@nodes_bp.route("/<node_id>/patch/check", methods=["POST"])
@login_required
def check_canvas_patch(node_id):
    node = _node_or_404(node_id)
    if not node.project.can_suggest(current_user):
        abort(403, t("node.no_access"))
    diagram = _canvas_or_400(node)

    try:
        dry_run_patch(diagram, _patch_from_request())
    except GraphError as exc:
        abort(400, str(exc))
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Резолв [[type:id]]-ссылок из markdown в человекочитаемые названия — см.
# app/static/js/wiki-links.js. Один batch-запрос на всю страницу разом,
# а не по одному вызову на каждую ссылку при рендере.
# ---------------------------------------------------------------------------
MAX_REFS_PER_REQUEST = 200


def _resolve_one(ref: dict, viewer) -> dict | None:
    """
    None — объект не найден ИЛИ недоступен текущему пользователю: то и
    другое выглядит для чужого черновика одинаково "нет такого", чтобы не
    подтверждать самим фактом ответа существование приватного объекта.
    """
    ref_type = ref.get("type")
    ref_id = ref.get("id")
    if not isinstance(ref_id, str):
        return None

    if ref_type == "page":
        node = db.session.get(Node, ref_id)
        if node is None or node.kind is not NodeKind.PAGE or not node.project.can_view(viewer):
            return None
        return {"type": "page", "id": ref_id, "title": node.title, "node_id": node.id}

    if ref_type == "block":
        block = db.session.get(FreeformBlock, ref_id)
        if block is None:
            return None
        node = db.session.get(Node, block.diagram_id)  # id канваса == id узла
        if node is None or not node.project.can_view(viewer):
            return None
        # У свободного блока название необязательно (может быть пустым —
        # это просто фигура) — тогда подписью служит название канваса.
        return {"type": "block", "id": ref_id, "title": block.title or node.title, "node_id": node.id}

    if ref_type == "suggestion":
        suggestion = db.session.get(Suggestion, ref_id)
        if suggestion is None or not suggestion.node.project.can_view(viewer):
            return None
        return {"type": "suggestion", "id": ref_id, "title": suggestion.title, "node_id": suggestion.node_id}

    return None


@nodes_bp.route("/resolve-refs", methods=["POST"])
@login_required
def resolve_refs():
    data = _json_body()
    refs = data.get("refs")
    if not isinstance(refs, list):
        abort(400, t("node.refs_must_be_list"))
    if len(refs) > MAX_REFS_PER_REQUEST:
        abort(400, t("node.too_many_refs", limit=MAX_REFS_PER_REQUEST))

    resolved = [_resolve_one(ref, current_user) for ref in refs if isinstance(ref, dict)]
    return jsonify([entry for entry in resolved if entry is not None])
