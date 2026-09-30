"""
HTTP API предложений (Suggestion) — упрощённый review-механизм без git-веток.
Любой авторизованный через Telegram человек, который видит проект, может
прислать идею и/или патч к любому узлу дерева (странице или канвасу);
принять или отклонить может только owner / editor.

Патч применяется по-разному в зависимости от node.kind: для canvas — список
операций graph_validator.apply_patch, для page — page_patch.apply_page_patch
({"content": "..."}). Сам этот роут не знает деталей ни того, ни другого —
он лишь выбирает нужную пару (apply, dry_run) по типу узла.
"""
import datetime as dt

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models.node import Node, NodeKind
from app.models.suggestion import Suggestion, SuggestionStatus
from app.services import graph_validator, page_patch
from app.services.i18n import t
from app.services.realtime import broadcast_diagram_state, broadcast_suggestions_changed

suggestions_bp = Blueprint("suggestions", __name__)

MAX_TITLE_LEN = 200
MAX_COMMENT_LEN = 2000

# node.kind -> (применить патч, «сухая» проверка патча, ошибка патча этого типа).
# Единая точка, которая знает, что канвас и страница патчатся по-разному —
# остальной код роута работает с ней, не разбирая kind сам.
_PATCH_BACKENDS = {
    NodeKind.CANVAS: (
        lambda node, patch: graph_validator.apply_patch(node.diagram, patch),
        lambda node, patch: graph_validator.dry_run_patch(node.diagram, patch),
        graph_validator.GraphError,
    ),
    NodeKind.PAGE: (
        page_patch.apply_page_patch,
        page_patch.dry_run_page_patch,
        page_patch.PageError,
    ),
}


def _node_or_404(node_id: str) -> Node:
    node = db.session.get(Node, node_id)
    if node is None:
        abort(404, t("node.not_found"))
    return node


def _suggestion_or_404(suggestion_id: str) -> Suggestion:
    suggestion = db.session.get(Suggestion, suggestion_id)
    if suggestion is None:
        abort(404, t("suggestion.not_found"))
    return suggestion


def _resolve(suggestion: Suggestion, status: SuggestionStatus) -> None:
    suggestion.status = status
    suggestion.resolved_at = dt.datetime.utcnow()
    suggestion.resolved_by_id = current_user.id


@suggestions_bp.route("/node/<node_id>", methods=["GET"])
def list_suggestions(node_id):
    """
    Участники проекта видят все предложения к узлу, остальные вошедшие —
    только свои, гости — ничего: идеи адресованы разработчикам, а не всем.
    """
    node = _node_or_404(node_id)
    viewer = current_user if current_user.is_authenticated else None
    if not node.project.can_view(viewer):
        abort(403, t("suggestion.no_access_to_node"))

    query = db.session.query(Suggestion).filter_by(node_id=node_id)
    if node.project.role_of(viewer) is None:
        if viewer is None:
            return jsonify([])
        query = query.filter_by(author_id=viewer.id)

    status_filter = request.args.get("status")
    if status_filter:
        try:
            query = query.filter_by(status=SuggestionStatus(status_filter))
        except ValueError:
            abort(400, t("suggestion.invalid_status"))
    return jsonify([s.public_dict() for s in query.order_by(Suggestion.created_at.desc()).all()])


@suggestions_bp.route("/node/<node_id>", methods=["POST"])
@login_required
def create_suggestion(node_id):
    """
    Предложение = текст и/или патч. Патч не применяется сразу: он проходит
    «сухой» прогон (заведомо сломанное предложение не принимается), а
    реальное применение — только при принятии editor'ом или владельцем.
    """
    node = _node_or_404(node_id)
    if not node.project.can_suggest(current_user):
        abort(403, t("suggestion.no_access_to_project"))

    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "").strip()[:MAX_TITLE_LEN]
    comment = str(data.get("comment") or "").strip()[:MAX_COMMENT_LEN]
    patch = data.get("patch")

    if not patch and not (title or comment):
        abort(400, t("suggestion.empty"))
    if patch:
        _, dry_run, error_cls = _PATCH_BACKENDS[node.kind]
        try:
            dry_run(node, patch)
        except error_cls as exc:
            abort(400, t("suggestion.patch_invalid", reason=str(exc)))

    suggestion = Suggestion(
        node_id=node.id,
        author_id=current_user.id,
        title=title or t("suggestion.default_title"),
        comment=comment,
        patch=patch,
    )
    db.session.add(suggestion)
    db.session.commit()

    broadcast_suggestions_changed(node)
    return jsonify(suggestion.public_dict()), 201


@suggestions_bp.route("/<suggestion_id>/accept", methods=["POST"])
@login_required
def accept_suggestion(suggestion_id):
    suggestion = _suggestion_or_404(suggestion_id)
    node = suggestion.node
    if not node.project.can_edit(current_user):
        abort(403, t("suggestion.only_editor_can_accept"))
    if suggestion.status != SuggestionStatus.PENDING:
        abort(400, t("suggestion.already_resolved"))

    if suggestion.patch:
        apply_patch, _, error_cls = _PATCH_BACKENDS[node.kind]
        try:
            apply_patch(node, suggestion.patch)
        except error_cls as exc:
            db.session.rollback()
            abort(409, t("suggestion.patch_no_longer_applies", reason=str(exc)))

    _resolve(suggestion, SuggestionStatus.ACCEPTED)
    db.session.commit()

    if suggestion.patch and node.kind is NodeKind.CANVAS:
        broadcast_diagram_state(node.diagram)
    broadcast_suggestions_changed(node)
    return jsonify(suggestion.public_dict())


@suggestions_bp.route("/<suggestion_id>/reject", methods=["POST"])
@login_required
def reject_suggestion(suggestion_id):
    suggestion = _suggestion_or_404(suggestion_id)
    if not suggestion.node.project.can_edit(current_user):
        abort(403, t("suggestion.only_editor_can_reject"))
    if suggestion.status != SuggestionStatus.PENDING:
        abort(400, t("suggestion.already_resolved"))

    _resolve(suggestion, SuggestionStatus.REJECTED)
    db.session.commit()

    broadcast_suggestions_changed(suggestion.node)
    return jsonify(suggestion.public_dict())
