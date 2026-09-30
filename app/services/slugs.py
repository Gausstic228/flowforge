"""
Slug проекта (site.com/<slug>): нормализация и проверка формата.
Чистые функции без БД — проверка занятости живёт в routes/projects.py.
"""
import re

MIN_SLUG_LEN = 3
MAX_SLUG_LEN = 64

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Пути, которые уже занимает само приложение: статический маршрут
# выигрывает у /<slug>, поэтому проект с таким slug был бы недоступен.
RESERVED_SLUGS = frozenset({
    "api", "auth", "static", "explore", "dashboard", "p",
    "login", "logout", "admin", "health", "favicon",
})

# Транслитерация украинской и русской кириллицы, чтобы название
# «Управління договорами» давало читаемый slug, а не случайный набор символов.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ь": "", "ъ": "", "ы": "y", "э": "e", "ю": "iu",
    "я": "ia", "ё": "e",
}


def slugify(raw: str) -> str:
    """Приводит произвольный текст к виду a-z0-9 через дефисы (может вернуть пустую строку)."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in raw.strip().lower())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:MAX_SLUG_LEN].strip("-")


def is_valid_slug(slug: str) -> bool:
    return MIN_SLUG_LEN <= len(slug) <= MAX_SLUG_LEN and bool(_SLUG_RE.match(slug))


def is_reserved(slug: str) -> bool:
    return slug in RESERVED_SLUGS
