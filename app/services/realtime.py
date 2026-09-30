"""
Realtime-слой FlowForge: Flask-SocketIO + Redis.

Разделение ответственности:
  * СТРУКТУРА диаграммы меняется только через HTTP (POST /api/nodes/<id>/patch
    и принятие предложений) и рассылается комнате событием diagram_state.
  * Сокет несёт только эфемерное: позицию блока при перетаскивании, курсоры,
    присутствие (кто онлайн) и сигналы «список предложений изменился».

Комната = id узла-канваса (Node.id == FreeformDiagram.id, они совпадают по
построению — см. models/diagram.py), а не отдельный "diagram_id": одно дерево
проекта, один и тот же id использует и навигация по дереву, и realtime.

Redis используется в двух ролях:
  1. message_queue у SocketIO (см. app/__init__.py) — шина между процессами
     сервера, чтобы событие дошло до клиента на любом процессе.
  2. Присутствие: sorted set presence:canvas:<node_id> (участник -> время
     последнего сигнала). Клиент шлёт presence_ping каждые ~20 с, запись
     старше PRESENCE_TTL считается устаревшей — «онлайн» переживает любое
     время сессии и сам очищается после обрыва связи.
"""
import time
from dataclasses import dataclass

import redis
from flask import current_app, request
from flask_login import current_user
from flask_socketio import emit, join_room

from app import db, socketio
from app.models.diagram import FreeformBlock, FreeformDiagram
from app.models.node import Node, NodeKind
from app.models.user import User
from app.services.graph_validator import parse_coordinate
from app.services.i18n import t

PRESENCE_TTL = 45  # секунд без presence_ping -> участник считается ушедшим

_redis_client = None


def _redis() -> redis.Redis:
    """Ленивая инициализация: конфиг приложения читается при первом обращении."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(current_app.config["REDIS_URL"], decode_responses=True)
    return _redis_client


def room_name(node_id: str) -> str:
    return f"canvas:{node_id}"


def _presence_key(node_id: str) -> str:
    return f"presence:canvas:{node_id}"


# ---------------------------------------------------------------------------
# Состояние и рассылки (используются и HTTP-роутами)
# ---------------------------------------------------------------------------
def diagram_payload(diagram: FreeformDiagram) -> dict:
    """Полное актуальное состояние графа + сводка проверки — один формат для HTTP и сокета."""
    return {"graph": diagram.to_graph_dict(), "validation": diagram.validation_summary()}


def broadcast_diagram_state(diagram: FreeformDiagram, payload: dict | None = None) -> None:
    """Разослать состояние всем в комнате канваса (включая автора изменения)."""
    socketio.emit("diagram_state", payload or diagram_payload(diagram), room=room_name(diagram.id))


def broadcast_suggestions_changed(node: Node) -> None:
    socketio.emit("suggestions_changed", {"node_id": node.id}, room=room_name(node.id))


# ---------------------------------------------------------------------------
# Присутствие
# ---------------------------------------------------------------------------
def _touch_presence(node_id: str, user_id: int) -> bool:
    """Отмечает участника «жив». True, если он до этого не числился онлайн."""
    r = _redis()
    key = _presence_key(node_id)
    now = time.time()
    last_seen = r.zscore(key, str(user_id))
    r.zadd(key, {str(user_id): now})
    r.expire(key, PRESENCE_TTL * 4)  # уборка канвасов, которые все покинули
    return last_seen is None or last_seen < now - PRESENCE_TTL


def _online_users(node_id: str) -> list[dict]:
    r = _redis()
    key = _presence_key(node_id)
    r.zremrangebyscore(key, 0, time.time() - PRESENCE_TTL)
    user_ids = [int(uid) for uid in r.zrange(key, 0, -1)]
    if not user_ids:
        return []
    users = db.session.query(User).filter(User.id.in_(user_ids)).all()
    return [user.public_dict() for user in users]


# ---------------------------------------------------------------------------
# Соединения. Реестр живёт в памяти процесса: сокет всегда обслуживается тем
# процессом, к которому подключился, поэтому per-process словаря достаточно.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Connection:
    node_id: str
    user_id: int | None  # None — гость (смотрит публичный канвас без входа)
    can_edit: bool


_connections: dict[str, _Connection] = {}


def _access(node_id):
    """(диаграмма, can_edit) для текущего пользователя, или (None, False)."""
    if not isinstance(node_id, str):
        return None, False
    node = db.session.get(Node, node_id)
    if node is None or node.kind is not NodeKind.CANVAS or node.diagram is None:
        return None, False
    if not node.project.can_view(current_user):
        return None, False
    return node.diagram, node.project.can_edit(current_user)


@socketio.on("join_diagram")
def on_join_diagram(data):
    node_id = (data or {}).get("node_id")
    diagram, can_edit = _access(node_id)
    if diagram is None:
        emit("server_error", {"message": t("realtime.no_diagram_access")})
        return

    user_id = current_user.id if current_user.is_authenticated else None
    _connections[request.sid] = _Connection(node_id, user_id, can_edit)
    join_room(room_name(node_id))

    is_new_presence = user_id is not None and _touch_presence(node_id, user_id)

    # Единственный «тяжёлый» пакет за сессию, дальше только дельты.
    emit("diagram_state", {**diagram_payload(diagram), "online": _online_users(node_id)})
    if is_new_presence:
        emit("presence_joined", current_user.public_dict(), room=room_name(node_id), include_self=False)


@socketio.on("presence_ping")
def on_presence_ping(_data=None):
    connection = _connections.get(request.sid)
    if connection is None or connection.user_id is None:
        return
    if _touch_presence(connection.node_id, connection.user_id):
        emit("presence_joined", current_user.public_dict(),
             room=room_name(connection.node_id), include_self=False)


@socketio.on("cursor_moved")
def on_cursor_moved(data):
    """Часто отправляемое лёгкое событие: без БД и без Redis."""
    connection = _connections.get(request.sid)
    if connection is None or connection.user_id is None:
        return
    try:
        x = parse_coordinate((data or {}).get("x"))
        y = parse_coordinate((data or {}).get("y"))
    except (TypeError, ValueError):
        return
    emit("cursor_moved", {"user_id": connection.user_id, "x": x, "y": y},
         room=room_name(connection.node_id), include_self=False)


@socketio.on("block_moved")
def on_block_moved(data):
    """
    Во время перетаскивания клиент шлёт block_moved(final=false) — только
    рассылка коллегам. По отпусканию кнопки — final=true: позиция
    сохраняется в БД (с повторной проверкой прав) и тоже рассылается.
    """
    connection = _connections.get(request.sid)
    if connection is None or not connection.can_edit:
        return
    data = data or {}
    try:
        x = parse_coordinate(data.get("x"))
        y = parse_coordinate(data.get("y"))
    except (TypeError, ValueError):
        return
    block_id = data.get("block_id")

    if data.get("final"):
        diagram, can_edit = _access(connection.node_id)
        if diagram is None or not can_edit:
            emit("server_error", {"message": t("realtime.no_edit_permission")})
            return
        block = db.session.get(FreeformBlock, block_id) if isinstance(block_id, str) else None
        if block is None or block.diagram_id != diagram.id:
            return
        block.pos_x, block.pos_y = x, y
        db.session.commit()

    emit("block_moved", {"block_id": block_id, "x": x, "y": y},
         room=room_name(connection.node_id), include_self=False)


@socketio.on("disconnect")
def on_disconnect():
    connection = _connections.pop(request.sid, None)
    if connection is None or connection.user_id is None:
        return
    _redis().zrem(_presence_key(connection.node_id), str(connection.user_id))
    socketio.emit("presence_left", {"user_id": connection.user_id}, room=room_name(connection.node_id))
