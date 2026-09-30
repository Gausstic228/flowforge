"""Мелкие общие помощники моделей."""
import datetime as dt
import uuid


def utcnow() -> dt.datetime:
    """Текущее время UTC без tzinfo: колонки DateTime хранят naive UTC."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    """32 hex-символа — такой же формат id клиент может назначать новым сущностям сам."""
    return uuid.uuid4().hex
