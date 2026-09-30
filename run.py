import eventlet

eventlet.monkey_patch()

import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app, socketio, db

app = create_app()

# Автоматическое создание таблиц при запуске
with app.app_context():
    # ВАЖНО: Импортируем модели, чтобы SQLAlchemy «увидела» класс User и другие таблицы
    # (укажите правильный путь к вашему файлу с моделями, например app.models или app.models.user)
    try:
        from app import models  # или: import app.models
        db.create_all()
        print("База данных успешно инициализирована, таблицы созданы.")
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)