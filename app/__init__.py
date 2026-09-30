"""
FlowForge — фабрика Flask-приложения.

Здесь создаются все расширения (БД, сокеты, логин-менеджер) и
регистрируются blueprints. Конфигурация приходит из окружения
(см. config.py и .env.example) — Python, PostgreSQL и Redis
запускаются локально, без Docker (см. README.md).
"""
import os

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_socketio import SocketIO

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# message_queue=redis:// — это то, что позволяет нескольким процессам
# сервера (если их несколько) обмениваться событиями сокетов между
# собой через Redis Pub/Sub. Без него realtime работал бы только в
# пределах одного процесса.
socketio = SocketIO(cors_allowed_origins="*")


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login_page"

    socketio.init_app(
        app,
        message_queue=app.config["REDIS_URL"],
        cors_allowed_origins="*",
    )

    from app.routes.auth import auth_bp
    from app.routes.projects import projects_bp
    from app.routes.nodes import nodes_bp
    from app.routes.suggestions import suggestions_bp
    from app.routes.main import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(nodes_bp, url_prefix="/api/nodes")
    app.register_blueprint(suggestions_bp, url_prefix="/api/suggestions")

    # Регистрируем обработчики WebSocket-событий (join_diagram, block_moved, cursor_moved...)
    from app.services import realtime  # noqa: F401  (регистрирует @socketio.on)

    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.services.i18n import current_lang, all_translations_for_frontend, available_languages
    from flask_login import current_user

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        """
        Единая точка: любой abort(code, "текст") из роутов /api/* должен
        дойти до фронтенда как JSON {"message": "текст"}, а не как
        HTML-страница ошибки werkzeug по умолчанию — иначе
        app/static/js/api-client.js не сможет её распарсить.
        Страницы (не /api/*) получают обычный HTML, как и раньше.
        """
        if request.path.startswith("/api/"):
            response = jsonify(message=error.description)
            response.status_code = error.code
            return response
        return error

    @app.context_processor
    def inject_i18n():
        """
        Делает current_lang/translations доступными во ВСЕХ шаблонах
        без ручного прокидывания в каждый render_template(). Именно
        отсюда base.html берёт window.FF_I18N для фронтенд-JS.
        """
        return {
            "current_lang": current_lang(),
            "translations": all_translations_for_frontend(),
            "available_languages": available_languages(),
            "current_user_json": (
                current_user.public_dict() if current_user.is_authenticated else None
            ),
        }

    return app
