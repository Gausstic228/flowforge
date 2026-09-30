"""
Страницы (HTML), которые отдаёт сервер. Один полноэкранный редактор
(app/templates/editor.html) на весь проект: дерево узлов слева, рабочая
область — markdown-страница или канвас, смотря какой узел открыт. Какой
узел показать первым — решает JS на фронте (по умолчанию титульный лист,
project.root_node_id), сервер лишь передаёт id проекта и, если он есть в
URL, id конкретного узла для открытия напрямую по глубокой ссылке.
"""
from flask import Blueprint, abort, render_template
from flask_login import current_user

from app import db
from app.models.node import Node
from app.models.project import Project

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return render_template("dashboard.html")
    return render_template("landing.html")


@main_bp.route("/dashboard")
def dashboard():
    if not current_user.is_authenticated:
        return render_template("landing.html")
    return render_template("dashboard.html")


@main_bp.route("/explore")
def explore():
    """Публичный каталог — доступен без логина."""
    return render_template("explore.html")


def _open_project(project, open_node_id=None):
    viewer = current_user if current_user.is_authenticated else None
    if not project.can_view(viewer):
        abort(403)
    root = db.session.query(Node).filter_by(project_id=project.id, parent_id=None).first()
    return render_template(
        "editor.html",
        project=project,
        root_node_id=root.id if root else None,
        open_node_id=open_node_id,
    )


@main_bp.route("/p/<int:project_id>")
def project_page_by_id(project_id):
    """
    Доступ по числовому id — для приватных проектов, у которых ещё нет (и
    может не быть никогда) slug. Более длинная, но всегда рабочая ссылка.
    """
    project = db.session.get(Project, project_id)
    if project is None:
        abort(404)
    return _open_project(project)


@main_bp.route("/p/<int:project_id>/<node_id>")
def project_node_page_by_id(project_id, node_id):
    """Глубокая ссылка сразу на конкретный узел дерева (страницу или канвас)."""
    project = db.session.get(Project, project_id)
    node = db.session.get(Node, node_id)
    if project is None or node is None or node.project_id != project.id:
        abort(404)
    return _open_project(project, open_node_id=node_id)


@main_bp.route("/<slug>")
def project_page(slug):
    """
    Прямой заход по slug: site.com/<slug>. Открывает проект на титульном
    листе — короткая, запоминающаяся ссылка без /api/projects/<id>/....
    """
    project = Project.query.filter_by(slug=slug).first()
    if project is None:
        abort(404)
    return _open_project(project)


@main_bp.route("/<slug>/<node_id>")
def project_node_page(slug, node_id):
    """Глубокая ссылка на конкретный узел по slug проекта."""
    project = Project.query.filter_by(slug=slug).first()
    node = db.session.get(Node, node_id)
    if project is None or node is None or node.project_id != project.id:
        abort(404)
    return _open_project(project, open_node_id=node_id)
