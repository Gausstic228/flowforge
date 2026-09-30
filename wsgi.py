"""
Отдельный модуль для Flask CLI-команд (flask db migrate, flask db
upgrade, flask shell). run.py не подходит для этого: там monkey_patch
и socketio.run() — лишние и потенциально проблемные при обычных CLI-
командах, которым не нужен WebSocket-сервер.

Использование:
    export FLASK_APP=wsgi.py        # (или: set FLASK_APP=wsgi.py на Windows)
    flask db init                    # один раз, если папки migrations/versions ещё нет
    flask db migrate -m "init"
    flask db upgrade
"""
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()
