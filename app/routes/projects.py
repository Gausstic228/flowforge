"""
HTTP API для проектов. Права доступа (кто может смотреть/редактировать/
управлять) целиком живут в модели Project (can_view/can_edit/can_manage) —
роуты только вызывают их, это та же логика, что использует WebSocket-слой.
"""
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models.node import Node, NodeKind
from app.models.project import ExternalLink, Project, ProjectMember, Role, Visibility
from app.models.user import User
from app.services.i18n import t
from app.services.slugs import is_reserved, is_valid_slug, slugify

projects_bp = Blueprint("projects", __name__)

MAX_NAME_LEN = 200
MAX_DESCRIPTION_LEN = 4000
MAX_LINK_TITLE_LEN = 120
MAX_LINK_URL_LEN = 500
MAX_LINKS_PER_PROJECT = 30


def _json_body() -> dict:
    """
    request.get_json(force=True) без silent=True роняет 500 на пустом или
    не-JSON теле — здесь всегда мягкий разбор с явным 400 при мусоре.
    """
    data = request.get_json(silent=True, force=True)
    if data is None:
        abort(400, t("project.invalid_json_body"))
    return data


def _project_or_404(identifier: str) -> Project:
    """
    identifier — числовой id ИЛИ slug. Числовой slug невозможен по построению
    (slugify всегда требует хотя бы одну букву — см. is_valid_slug), поэтому
    "123" однозначно трактуется как id, а не как чей-то slug.
    """
    project = None
    if identifier.isdigit():
        project = db.session.get(Project, int(identifier))
    else:
        project = db.session.query(Project).filter_by(slug=identifier).first()
    if project is None:
        abort(404, t("project.not_found"))
    return project


def _unique_slug(base: str) -> str:
    """
    Первый свободный и не зарезервированный slug на основе base. is_reserved
    проверяется на КАЖДОМ кандидате (не только на исходном base) — иначе
    "explore-2" после занятого "explore" тоже мог бы случайно попасть на
    зарезервированный путь при повторных вызовах в будущем.
    """
    candidate = base
    suffix = 1
    while is_reserved(candidate) or db.session.query(Project).filter_by(slug=candidate).first():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _slug_from_input(raw: str) -> str:
    """slugify() + проверка итоговой формы; пустой/слишком короткий результат — ошибка 400."""
    candidate = slugify(raw)
    if not is_valid_slug(candidate):
        abort(400, t("project.invalid_slug"))
    return candidate


@projects_bp.route("", methods=["GET"])
@login_required
def list_my_projects():
    """Проекты, где текущий пользователь — владелец или участник."""
    owned = db.session.query(Project).filter_by(owner_id=current_user.id)
    member_ids = [m.project_id for m in current_user.memberships]
    member_projects = (
        db.session.query(Project).filter(Project.id.in_(member_ids)) if member_ids else []
    )

    seen = {}
    for project in list(owned) + list(member_projects):
        seen[project.id] = project
    ordered = sorted(seen.values(), key=lambda p: p.updated_at, reverse=True)
    return jsonify([p.public_dict(current_user) for p in ordered])


@projects_bp.route("/public", methods=["GET"])
def list_public_projects():
    """Общий каталог — доступен без авторизации, только PUBLIC-проекты."""
    projects = (
        db.session.query(Project)
        .filter_by(visibility=Visibility.PUBLIC)
        .order_by(Project.updated_at.desc())
        .all()
    )
    viewer = current_user if current_user.is_authenticated else None
    return jsonify([p.public_dict(viewer) for p in projects])


@projects_bp.route("", methods=["POST"])
@login_required
def create_project():
    """
    Без формы на старте: имя и описание необязательны — стандартный проект
    с чистого листа, переименовать можно позже прямо в дереве или на самом
    титульном листе. Единственное, что создаётся сразу, — корневой узел
    (kind=page, parent_id=None): он и есть титульный лист проекта.
    """
    data = _json_body()
    name = str(data.get("name") or "").strip()[:MAX_NAME_LEN] or t("project.default_name")

    project = Project(
        name=name,
        description=str(data.get("description") or "").strip()[:MAX_DESCRIPTION_LEN],
        owner_id=current_user.id,
    )
    db.session.add(project)
    db.session.flush()  # получить project.id для корневого узла ниже

    root = Node(project_id=project.id, parent_id=None, kind=NodeKind.PAGE, title=name, position=0)
    db.session.add(root)

    db.session.commit()
    return jsonify(project.public_dict(current_user)), 201


@projects_bp.route("/<identifier>", methods=["GET"])
def get_project(identifier):
    project = _project_or_404(identifier)
    viewer = current_user if current_user.is_authenticated else None
    if not project.can_view(viewer):
        abort(403, t("project.no_access"))

    payload = project.public_dict(viewer)
    root = db.session.query(Node).filter_by(project_id=project.id, parent_id=None).first()
    payload["root_node_id"] = root.id if root else None
    return jsonify(payload)


@projects_bp.route("/<identifier>/tree", methods=["GET"])
def get_project_tree(identifier):
    """
    Дерево целиком одним запросом — плоский список узлов (не вложенный),
    сборку иерархии по parent_id делает app/static/js/tree-nav.js: дерево
    редко бывает настолько большим, чтобы это было проблемой, а плоский
    список проще кэшировать и обновлять по месту после одной правки.
    """
    project = _project_or_404(identifier)
    viewer = current_user if current_user.is_authenticated else None
    if not project.can_view(viewer):
        abort(403, t("project.no_access"))

    nodes = db.session.query(Node).filter_by(project_id=project.id).order_by(Node.position).all()
    return jsonify([n.public_dict() for n in nodes])


@projects_bp.route("/<identifier>/visibility", methods=["PATCH"])
@login_required
def set_visibility(identifier):
    """
    Смена видимости — единственное место, где выдаётся/меняется slug.
    PRIVATE не требует slug. При переходе в LINK/PUBLIC slug создаётся из
    названия, если его ещё нет; уже выданный slug остаётся за проектом даже
    при возврате в PRIVATE (не "протухает", если открыть доступ повторно).
    """
    project = _project_or_404(identifier)
    if not project.can_manage(current_user):
        abort(403, t("project.only_owner_can_manage_visibility"))

    data = _json_body()
    try:
        new_visibility = Visibility(data.get("visibility"))
    except ValueError:
        abort(400, t("project.invalid_visibility"))

    requested_slug = data.get("slug")
    if requested_slug:
        candidate = _slug_from_input(requested_slug)
        if candidate != project.slug:
            if is_reserved(candidate) or db.session.query(Project).filter(
                Project.slug == candidate, Project.id != project.id
            ).first():
                abort(409, t("project.slug_taken"))
            project.slug = candidate
    elif new_visibility != Visibility.PRIVATE and not project.slug:
        project.slug = _unique_slug(_slug_from_input(project.name))

    project.visibility = new_visibility
    db.session.commit()
    return jsonify(project.public_dict(current_user))


@projects_bp.route("/<identifier>/members", methods=["POST"])
@login_required
def add_member(identifier):
    """Добавить участника по его Telegram username. Роль по умолчанию — viewer."""
    project = _project_or_404(identifier)
    if not project.can_manage(current_user):
        abort(403, t("project.only_owner_can_manage_team"))

    data = _json_body()
    username = str(data.get("username") or "").lstrip("@").strip()
    if not username:
        abort(400, t("project.username_required"))

    user = db.session.query(User).filter_by(username=username).first()
    if user is None:
        abort(404, t("project.member_never_logged_in"))
    if user.id == project.owner_id:
        abort(400, t("project.owner_already_has_access"))

    role_raw = data.get("role", Role.VIEWER.value)
    if role_raw not in (Role.EDITOR.value, Role.VIEWER.value):
        abort(400, t("project.invalid_role"))
    role = Role(role_raw)

    existing = next((m for m in project.members if m.user_id == user.id), None)
    if existing:
        existing.role = role
    else:
        db.session.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))

    db.session.commit()
    return jsonify(project.public_dict(current_user))


@projects_bp.route("/<identifier>/members/<int:user_id>", methods=["DELETE"])
@login_required
def remove_member(identifier, user_id):
    project = _project_or_404(identifier)
    if not project.can_manage(current_user):
        abort(403, t("project.only_owner_can_manage_team"))

    member = next((m for m in project.members if m.user_id == user_id), None)
    if member is None:
        abort(404, t("project.member_not_found"))

    db.session.delete(member)
    db.session.commit()
    return jsonify(project.public_dict(current_user))


@projects_bp.route("/<identifier>/links", methods=["POST"])
@login_required
def add_link(identifier):
    """
    Произвольная ссылка проекта. Без нормирования под GitHub/PyPI — просто
    заголовок и адрес, владелец сам решает, что и как назвать.
    """
    project = _project_or_404(identifier)
    if not project.can_manage(current_user):
        abort(403, t("project.only_owner_can_manage_links"))
    if len(project.links) >= MAX_LINKS_PER_PROJECT:
        abort(400, t("project.too_many_links", limit=MAX_LINKS_PER_PROJECT))

    data = _json_body()
    title = str(data.get("title") or "").strip()[:MAX_LINK_TITLE_LEN]
    url = str(data.get("url") or "").strip()[:MAX_LINK_URL_LEN]
    if not title or not url:
        abort(400, t("project.link_needs_title_and_url"))
    if not (url.startswith("http://") or url.startswith("https://")):
        abort(400, t("project.link_must_be_http"))

    db.session.add(
        ExternalLink(project_id=project.id, title=title, url=url, position=len(project.links))
    )
    db.session.commit()
    return jsonify(project.public_dict(current_user)), 201


@projects_bp.route("/<identifier>/links/<int:link_id>", methods=["DELETE"])
@login_required
def remove_link(identifier, link_id):
    project = _project_or_404(identifier)
    if not project.can_manage(current_user):
        abort(403, t("project.only_owner_can_manage_links"))

    link = db.session.get(ExternalLink, link_id)
    if link is None or link.project_id != project.id:
        abort(404, t("project.link_not_found"))

    db.session.delete(link)
    db.session.commit()
    return jsonify(project.public_dict(current_user))
