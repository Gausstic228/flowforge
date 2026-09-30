"""
Единая точка импорта моделей — flask-migrate/Alembic должен видеть все
модели при autogenerate, поэтому они собираются здесь.
"""
from app.models.user import User  # noqa: F401
from app.models.project import Project, ProjectMember, ExternalLink, Visibility, Role  # noqa: F401
from app.models.node import Node, NodeKind  # noqa: F401
from app.models.diagram import (  # noqa: F401
    FreeformDiagram, FreeformBlock, ConnectionPoint, Connector, BlockShape,
)
from app.models.suggestion import Suggestion, SuggestionStatus  # noqa: F401
