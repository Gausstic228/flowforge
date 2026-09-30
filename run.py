"""
Точка входа FlowForge.

Запуск локально (после `pip install -r requirements.txt` и настройки
PostgreSQL/Redis — см. README.md):

    python run.py
"""
import eventlet

eventlet.monkey_patch()

import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app, socketio, db
from flask_migrate import upgrade  # Импортируем функцию миграции

app = create_app()

# Автоматически применяем миграции (создаем таблицы) при старте на Render
with app.app_context():
    try:
        upgrade()
        print("Database migrations applied successfully.")
    except Exception as e:
        print(f"Error applying migrations: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)