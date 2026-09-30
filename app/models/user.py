"""
Пользователь FlowForge = аккаунт Telegram. Пароля нет: единственный способ
входа — Telegram OIDC (см. app/routes/auth.py).
"""
from flask_login import UserMixin

from app import db
from app.models._util import utcnow


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Числовой Telegram ID (claim `id` из id_token) — уникален и неизменен.
    telegram_id = db.Column(db.String(64), unique=True, nullable=False, index=True)

    # @username может отсутствовать или смениться, поэтому не уникален:
    # приглашение по нику берёт самого недавно заходившего владельца ника.
    username = db.Column(db.String(64), nullable=True, index=True)
    display_name = db.Column(db.String(128), nullable=False, default="")
    avatar_url = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    last_login_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    memberships = db.relationship(
        "ProjectMember", back_populates="user", cascade="all, delete-orphan"
    )
    # У Suggestion два внешних ключа на users (автор и тот, кто разобрал),
    # поэтому связь обязана явно указать, какой из них она использует.
    suggestions = db.relationship(
        "Suggestion", foreign_keys="Suggestion.author_id", back_populates="author"
    )

    def public_dict(self) -> dict:
        """Что можно безопасно показать другим участникам (telegram_id не отдаётся)."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
        }

    def __repr__(self) -> str:
        return f"<User {self.username or self.telegram_id}>"
