"""
Suggestion — идея или черновик правки от человека без прав editor,
адресованная разработчикам проекта. Сознательно простой review без git-веток:
текст (заголовок + комментарий) + необязательный патч + статус.

Ссылается на Node, а не жёстко на диаграмму: с расширением дерева на
markdown-страницы предложение может касаться и правки текста страницы, и
правки холста — форма патча зависит от node.kind (см. graph_validator.py
для canvas и app/services/page_patch.py для page).
"""
import enum

from app import db
from app.models._util import new_id, utcnow


class SuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Suggestion(db.Model):
    __tablename__ = "suggestions"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    node_id = db.Column(db.String(32), db.ForeignKey("nodes.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False, default="")
    comment = db.Column(db.Text, nullable=False, default="")

    # Пустой список/null — идея без конкретной правки, просто текст для
    # разработчиков. Формат непустого патча зависит от node.kind: для
    # canvas — список операций graph_validator.apply_patch; для page —
    # {"content": "новый markdown-текст целиком"} (см. page_patch.py).
    patch = db.Column(db.JSON, nullable=True)

    status = db.Column(
        db.Enum(SuggestionStatus, native_enum=False),
        nullable=False,
        default=SuggestionStatus.PENDING,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    node = db.relationship("Node")
    author = db.relationship("User", foreign_keys=[author_id], back_populates="suggestions")
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id])

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "author": self.author.public_dict(),
            "title": self.title,
            "comment": self.comment,
            "patch": self.patch,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
