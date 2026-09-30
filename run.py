"""
Точка входа FlowForge.

Запуск локально (после `pip install -r requirements.txt` и настройки
PostgreSQL/Redis — см. README.md):

    python run.py

Обычный `flask run` здесь не подходит: WebSocket (Flask-SocketIO)
корректно работает только через собственный сервер socketio.run(),
который патчит сеть под eventlet и понимает Upgrade-запросы. Именно
поэтому этот файл — единственная предполагаемая точка запуска.
"""
import eventlet

# monkey_patch ДОЛЖЕН быть первой строчкой, которая что-либо делает —
# до импорта requests/psycopg2/redis и т.д. Иначе часть стандартной
# библиотеки (socket, threading) останется синхронной, и eventlet не
# сможет параллелить WebSocket-соединения так, как задумано.
eventlet.monkey_patch()

import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
