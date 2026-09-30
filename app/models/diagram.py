"""
Свободная диаграмма FlowForge — блоки как в UML/Miro: форму, цвет, подпись
и точки соединения выбирает человек, а не программа. Программа фиксирует
только направленность связи (откуда -> куда существующий блок), а не её
смысл — в отличие от предыдущей версии продукта, здесь нет типизированных
портов input/control/output/mechanism и никакой ICOM-валидации: пользователь
сам решает, что означает линия между двумя его фигурами.
"""
import enum

from app import db
from app.models._util import new_id, utcnow

DEFAULT_BLOCK_WIDTH = 160.0
DEFAULT_BLOCK_HEIGHT = 80.0


class BlockShape(str, enum.Enum):
    RECTANGLE = "rectangle"
    ROUNDED = "rounded"
    ELLIPSE = "ellipse"
    DIAMOND = "diamond"
    HEXAGON = "hexagon"
    PARALLELOGRAM = "parallelogram"


class FreeformDiagram(db.Model):
    __tablename__ = "freeform_diagrams"

    # id = id узла-канваса, к которому диаграмма принадлежит 1-к-1:
    # у диаграммы нет отдельной "жизни" вне своего узла дерева.
    id = db.Column(db.String(32), db.ForeignKey("nodes.id"), primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    node = db.relationship("Node", back_populates="diagram")
    blocks = db.relationship(
        "FreeformBlock", back_populates="diagram", cascade="all, delete-orphan", lazy="selectin"
    )
    connectors = db.relationship(
        "Connector", back_populates="diagram", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_graph_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "shapes": [shape.value for shape in BlockShape],
            "blocks": [block.public_dict() for block in self.blocks],
            "connectors": [connector.public_dict() for connector in self.connectors],
        }

    def validation_summary(self) -> dict:
        from app.services.graph_validator import summarize  # отложенный импорт: цикл модулей
        return summarize(self)


class FreeformBlock(db.Model):
    __tablename__ = "freeform_blocks"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    diagram_id = db.Column(
        db.String(32), db.ForeignKey("freeform_diagrams.id"), nullable=False, index=True
    )

    title = db.Column(db.String(300), nullable=False, default="")
    shape = db.Column(db.Enum(BlockShape, native_enum=False), nullable=False, default=BlockShape.ROUNDED)
    # Свой цвет — hex-строка "#rrggbb"; фон и текст блока в интерфейсе
    # рендерятся от этого одного значения, программа не навязывает палитру.
    color = db.Column(db.String(7), nullable=False, default="#9333ea")

    pos_x = db.Column(db.Float, nullable=False, default=0.0)
    pos_y = db.Column(db.Float, nullable=False, default=0.0)
    width = db.Column(db.Float, nullable=False, default=DEFAULT_BLOCK_WIDTH)
    height = db.Column(db.Float, nullable=False, default=DEFAULT_BLOCK_HEIGHT)
    z_index = db.Column(db.Integer, nullable=False, default=0)  # порядок наложения при перекрытии

    diagram = db.relationship("FreeformDiagram", back_populates="blocks")
    points = db.relationship(
        "ConnectionPoint", back_populates="block", cascade="all, delete-orphan", lazy="selectin"
    )

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "shape": self.shape.value,
            "color": self.color,
            "x": self.pos_x,
            "y": self.pos_y,
            "width": self.width,
            "height": self.height,
            "z_index": self.z_index,
            "points": [point.public_dict() for point in self.points],
        }


class ConnectionPoint(db.Model):
    """
    Точка на блоке, откуда может идти связь. rel_x/rel_y — доля (0..1) от
    ширины/высоты блока, а не абсолютные координаты: так точка остаётся на
    своём месте на фигуре при переносе или изменении размера блока.
    Сколько точек и где — решает человек, программа не навязывает "4 стороны".
    """
    __tablename__ = "connection_points"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    block_id = db.Column(db.String(32), db.ForeignKey("freeform_blocks.id"), nullable=False, index=True)

    rel_x = db.Column(db.Float, nullable=False, default=0.5)
    rel_y = db.Column(db.Float, nullable=False, default=0.5)
    label = db.Column(db.String(120), nullable=False, default="")

    block = db.relationship("FreeformBlock", back_populates="points")

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "block_id": self.block_id,
            "rel_x": self.rel_x,
            "rel_y": self.rel_y,
            "label": self.label,
        }


class Connector(db.Model):
    """
    Связь между двумя блоками (через конкретную точку или "просто от блока",
    если from_point_id/to_point_id не заданы). Подпись, цвет, толщина, стиль
    линии (сплошная/пунктир) и стрелка на конце — всё свободно, программа
    хранит их как данные и не придаёт им смысла.
    """
    __tablename__ = "connectors"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    diagram_id = db.Column(
        db.String(32), db.ForeignKey("freeform_diagrams.id"), nullable=False, index=True
    )

    from_block_id = db.Column(
        db.String(32), db.ForeignKey("freeform_blocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_block_id = db.Column(
        db.String(32), db.ForeignKey("freeform_blocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_point_id = db.Column(
        db.String(32), db.ForeignKey("connection_points.id", ondelete="SET NULL"), nullable=True
    )
    to_point_id = db.Column(
        db.String(32), db.ForeignKey("connection_points.id", ondelete="SET NULL"), nullable=True
    )

    label = db.Column(db.String(200), nullable=False, default="")
    color = db.Column(db.String(7), nullable=False, default="#5c6178")
    dashed = db.Column(db.Boolean, nullable=False, default=False)
    arrow = db.Column(db.Boolean, nullable=False, default=True)

    diagram = db.relationship("FreeformDiagram", back_populates="connectors")
    from_block = db.relationship("FreeformBlock", foreign_keys=[from_block_id])
    to_block = db.relationship("FreeformBlock", foreign_keys=[to_block_id])
    from_point = db.relationship("ConnectionPoint", foreign_keys=[from_point_id])
    to_point = db.relationship("ConnectionPoint", foreign_keys=[to_point_id])

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "from_block": self.from_block_id,
            "to_block": self.to_block_id,
            "from_point": self.from_point_id,
            "to_point": self.to_point_id,
            "label": self.label,
            "color": self.color,
            "dashed": self.dashed,
            "arrow": self.arrow,
        }
