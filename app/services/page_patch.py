"""
page_patch — применение предложенной правки к markdown-странице.

Симметрично graph_validator.py (apply_patch/dry_run_patch), но для страниц
патч — это не список операций, а просто {"content": "новый текст целиком"}:
markdown — сплошной текст, а не структурированный граф, покомандно его
редактировать нет смысла — черновик правки лучше всего виден как "было/стало"
целиком, а не как diff операций.
"""
from __future__ import annotations

from app import db
from app.models._util import utcnow
from app.models.node import Node, NodeKind
from app.services.i18n import t

# Щедрый лимит на markdown-текст страницы, а не жёсткая стена. Общая
# константа для прямого сохранения (routes/nodes.py) и для патчей отсюда —
# единственное место, которое решает, что такое "слишком длинная страница".
MAX_CONTENT_LEN = 500_000


class PageError(Exception):
    """Ожидаемая ошибка: текст уже переведён и предназначен пользователю."""


def apply_page_patch(node: Node, patch) -> None:
    if node.kind is not NodeKind.PAGE:
        raise PageError(t("node.not_a_page"))
    if not isinstance(patch, dict) or "content" not in patch:
        raise PageError(t("suggestion.page_patch_needs_content"))

    content = patch["content"]
    if not isinstance(content, str):
        raise PageError(t("suggestion.page_patch_needs_content"))
    if len(content) > MAX_CONTENT_LEN:
        raise PageError(t("node.content_too_large", limit=MAX_CONTENT_LEN))

    node.content = content
    node.updated_at = utcnow()
    node.project.updated_at = utcnow()


def dry_run_page_patch(node: Node, patch) -> None:
    """Проверяет патч на SAVEPOINT'е и ВСЕГДА откатывает его — в базе не остаётся следа."""
    nested = db.session.begin_nested()
    try:
        apply_page_patch(node, patch)
    finally:
        nested.rollback()
