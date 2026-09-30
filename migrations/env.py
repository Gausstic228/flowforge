import logging
from logging.config import fileConfig

from flask import current_app

from alembic import context

# Стандартный конфиг Alembic — читает migrations/alembic.ini.
config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():
    try:
        # Flask-SQLAlchemy >= 3
        return current_app.extensions["migrate"].db.engine
    except (TypeError, AttributeError):
        return current_app.extensions["migrate"].db.get_engine()


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())
target_db = current_app.extensions["migrate"].db


def get_metadata():
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Генерация SQL-скрипта миграции без подключения к БД (--sql режим)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=get_metadata(), literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Обычный режим — применяет/генерирует миграцию, подключаясь к реальной БД."""

    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("Изменений в моделях не найдено — миграция не создана.")

    conf_args = current_app.extensions["migrate"].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=get_metadata(), **conf_args
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
