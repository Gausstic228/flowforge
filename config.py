"""
Конфигурация FlowForge. Всё берётся из переменных окружения — так один
и тот же образ работает и локально (.env), и в Docker Compose, и в
проде (секреты через переменные окружения хостинга).
"""
import os


def _env(name: str, default=None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Обязательная переменная окружения {name} не задана. "
            f"Проверь .env файл (см. .env.example)."
        )
    return value


class Config:
    SECRET_KEY = _env("SECRET_KEY", "dev-secret-change-me-in-production")

    SQLALCHEMY_DATABASE_URI = _env(
        "DATABASE_URL",
        "postgresql://flowforge:flowforge@localhost:5432/flowforge",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")

    # --- Telegram OIDC ---
    # Получаются в @BotFather → Bot Settings → Web Login →
    # "Switch to OpenID Connect Login" (переключение необратимо).
    # TG_CLIENT_SECRET — это НЕ токен бота, отдельный секрет для OIDC.
    TELEGRAM_CLIENT_ID = _env("TELEGRAM_CLIENT_ID", "")
    TELEGRAM_CLIENT_SECRET = _env("TELEGRAM_CLIENT_SECRET", "")
    TELEGRAM_BOT_USERNAME = _env("TELEGRAM_BOT_USERNAME", "")

    # Куда Telegram редиректит после логина. Должен быть
    # зарегистрирован в BotFather как Allowed URL.
    TELEGRAM_REDIRECT_URI = _env(
        "TELEGRAM_REDIRECT_URI", "http://localhost:5000/auth/telegram/callback"
    )

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # В проде за HTTPS обязательно включить:
    SESSION_COOKIE_SECURE = _env("SESSION_COOKIE_SECURE", "false").lower() == "true"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
