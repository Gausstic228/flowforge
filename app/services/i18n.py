"""
i18n — переводы FlowForge.

Тексты не вшиты в код: они лежат как список ключ→строка в JSON-файлах
translations/<lang>.json рядом с app/ (см. корень репозитория). Здесь —
только механизм загрузки и подстановки, сами слова в этом файле не
живут ни строкой.

Использование в роуте/сервисе:
    from app.services.i18n import t
    abort(404, t("project.not_found"))
    raise GraphError(t("graph.block_not_found_in_diagram", id=block_id))

Язык определяется один раз за запрос (см. current_lang()) в таком
порядке приоритета: ?lang=xx в URL → cookie "flowforge_lang" →
заголовок Accept-Language → DEFAULT_LANG.
"""
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

from flask import g, has_request_context, request

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "translations"
DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "uk", "en")


@lru_cache(maxsize=None)
def _load_lang(lang: str) -> dict:
    """
    Читает translations/<lang>.json один раз и кэширует в памяти —
    файлы читаются с диска только при первом обращении к языку за
    всё время жизни процесса, дальше это чистый dict-lookup.
    """
    path = TRANSLATIONS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.pop("_meta", None)
    return data


@lru_cache(maxsize=1)
def available_languages() -> tuple[dict, ...]:
    """Для переключателя языка в шаблонах: [{"code": "ru", "name": "Русский"}, ...]."""
    result = []
    for lang in SUPPORTED_LANGS:
        path = TRANSLATIONS_DIR / f"{lang}.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            meta = json.load(fh).get("_meta", {})
        result.append({"code": lang, "name": meta.get("name", lang)})
    return tuple(result)


def current_lang() -> str:
    """
    Определяет язык текущего запроса и кэширует результат в flask.g,
    чтобы не пересчитывать его несколько раз за один запрос.
    """
    if not has_request_context():
        return DEFAULT_LANG
    if "lang" in g:
        return g.lang

    candidate = request.args.get("lang")
    if not candidate:
        candidate = request.cookies.get("flowforge_lang")
    if not candidate:
        best = request.accept_languages.best_match(SUPPORTED_LANGS)
        candidate = best

    g.lang = candidate if candidate in SUPPORTED_LANGS else DEFAULT_LANG
    return g.lang


def t(key: str, **kwargs) -> str:
    """
    Возвращает перевод по ключу для текущего языка запроса. Если ключ
    отсутствует в выбранном языке — падает на DEFAULT_LANG, а если и
    там нет — возвращает сам ключ (заметно в интерфейсе, что перевод
    не найден, вместо тихого краша).
    """
    lang = current_lang()
    template = _load_lang(lang).get(key)
    if template is None:
        template = _load_lang(DEFAULT_LANG).get(key, key)

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def all_translations_for_frontend() -> dict:
    """
    Отдаёт весь словарь текущего языка целиком — используется на
    страницах, чтобы JS на фронтенде (app/static/js) мог переводить
    динамически генерируемые элементы (сообщения валидации графа,
    подписи портов) без похода на сервер за каждой фразой.
    """
    return _load_lang(current_lang())
