"""
Project — контейнер верхнего уровня: видимость, короткая ссылка (site.com/<slug>),
команда и произвольные внешние ссылки. Права выдаются на уровне проекта.
"""
import enum

from app import db
from app.models._util import utcnow


class Visibility(str, enum.Enum):
    PRIVATE = "private"  # видят только участники
    LINK = "link"        # видит любой, у кого есть ссылка; в каталог не попадает
    PUBLIC = "public"    # видит любой; попадает в общий каталог


class Role(str, enum.Enum):
    OWNER = "owner"    # видимость, slug, команда, удаление проекта
    EDITOR = "editor"  # правит диаграмму, принимает и отклоняет предложения
    VIEWER = "viewer"  # смотрит и может присылать предложения


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")

    # Короткая ссылка. Выдаётся владельцем при выходе из PRIVATE и остаётся
    # за проектом (ссылка не «протухает», если проект снова закрыли).
    slug = db.Column(db.String(64), unique=True, nullable=True, index=True)

    visibility = db.Column(
        db.Enum(Visibility, native_enum=False), nullable=False, default=Visibility.PRIVATE
    )
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id])
    members = db.relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )
    # Всё дерево проекта — markdown-страницы и канвасы вперемешку, без
    # разделения на "диаграммы отдельно". Титульный лист — узел с
    # parent_id=None; ровно один такой узел на проект (создаётся вместе
    # с проектом, см. ProjectService.create в routes/projects.py).
    nodes = db.relationship(
        "Node", back_populates="project", cascade="all, delete-orphan"
    )
    links = db.relationship(
        "ExternalLink", back_populates="project", cascade="all, delete-orphan",
        order_by="ExternalLink.position",
    )

    # ------------------------------------------------------------------
    # Права — единая точка правды для HTTP-роутов и обработчиков WebSocket.
    # ------------------------------------------------------------------
    def role_of(self, user) -> Role | None:
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        if user.id == self.owner_id:
            return Role.OWNER
        for member in self.members:
            if member.user_id == user.id:
                return member.role
        return None

    def can_view(self, user) -> bool:
        if self.visibility in (Visibility.PUBLIC, Visibility.LINK):
            return True
        return self.role_of(user) is not None

    def can_edit(self, user) -> bool:
        return self.role_of(user) in (Role.OWNER, Role.EDITOR)

    def can_manage(self, user) -> bool:
        return self.role_of(user) is Role.OWNER

    def can_suggest(self, user) -> bool:
        """Присылать предложения может любой вошедший, кто вообще видит проект."""
        return bool(getattr(user, "is_authenticated", False)) and self.can_view(user)

    def public_dict(self, viewer=None) -> dict:
        role = self.role_of(viewer)
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "slug": self.slug,
            "visibility": self.visibility.value,
            "owner": self.owner.public_dict(),
            "role": role.value if role else None,
            # Что можно делать — решает сервер; фронтенд роли не «угадывает».
            "can": {
                "edit": role in (Role.OWNER, Role.EDITOR),
                "manage": role is Role.OWNER,
                "suggest": self.can_suggest(viewer),
            },
            "members": [member.public_dict() for member in self.members],
            "links": [link.public_dict() for link in self.links],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ProjectMember(db.Model):
    __tablename__ = "project_members"
    __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.Enum(Role, native_enum=False), nullable=False, default=Role.VIEWER)
    added_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    project = db.relationship("Project", back_populates="members")
    user = db.relationship("User", back_populates="memberships")

    def public_dict(self) -> dict:
        return {**self.user.public_dict(), "role": self.role.value}


class ExternalLink(db.Model):
    """
    Произвольная ссылка проекта: GitHub, PyPI, Notion, демо — что угодно.
    Сознательно без типа «github|pypi»: только название и адрес, порядок задаёт владелец.
    """
    __tablename__ = "external_links"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    project = db.relationship("Project", back_populates="links")

    def public_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "url": self.url}
