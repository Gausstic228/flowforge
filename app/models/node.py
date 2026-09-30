"""
Node — узел дерева проекта. Единое дерево для всего: markdown-страниц и
диаграмм. Титульный лист — узел с parent_id=None (у проекта он ровно один,
это сам корень); "Документація" может быть страницей с дочерней
диаграммой — то и другое лежит в одном дереве, без отдельного "режима".

kind="page"   -> content хранит markdown-текст, diagram пуст
kind="canvas" -> у узла есть ровно один FreeformDiagram (children.py: связь
                 1-к-1 через node.diagram, см. FreeformDiagram.node_id)
"""
import enum

from app import db
from app.models._util import new_id, utcnow


class NodeKind(str, enum.Enum):
    PAGE = "page"
    CANVAS = "canvas"


class Node(db.Model):
    __tablename__ = "nodes"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    parent_id = db.Column(db.String(32), db.ForeignKey("nodes.id"), nullable=True, index=True)

    kind = db.Column(db.Enum(NodeKind, native_enum=False), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    # Порядок среди узлов с тем же parent_id — задаёт человек, перетаскивая
    # в дереве; программа не решает, что "важнее".
    position = db.Column(db.Integer, nullable=False, default=0)

    # markdown-текст; заполнен только у kind=PAGE, у CANVAS всегда "".
    content = db.Column(db.Text, nullable=False, default="")

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    project = db.relationship("Project", back_populates="nodes")
    parent = db.relationship("Node", remote_side=[id], backref="children")
    diagram = db.relationship(
        "FreeformDiagram", back_populates="node", uselist=False, cascade="all, delete-orphan"
    )

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "kind": self.kind.value,
            "title": self.title,
            "position": self.position,
            "updated_at": self.updated_at.isoformat(),
        }

    def public_dict_with_content(self) -> dict:
        """Полная запись узла — для открытия страницы/канваса, а не только строки дерева."""
        payload = self.public_dict()
        if self.kind is NodeKind.PAGE:
            payload["content"] = self.content
        else:
            payload["diagram"] = self.diagram.to_graph_dict() if self.diagram else None
        return payload
