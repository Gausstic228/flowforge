# FlowForge

Полноэкранный редактор проекта: одно дерево узлов (титульный лист как
корень, markdown-страницы и свободные холсты вперемешку — не два разных
режима), авторизация только через Telegram (OIDC), совместная работа в
реальном времени через Flask-SocketIO + Redis. Данные — в PostgreSQL.
Никакого Docker: обычные локальные сервисы.

## Что внутри

- **Дерево проекта** (`app/models/node.py`) — узлы `page` (markdown) и
  `canvas` (свободная диаграмма), у каждого свои дети. Титульный лист —
  корневой узел без родителя.
- **Свободная диаграмма** (`app/models/diagram.py`) — блоки произвольной
  формы и цвета (`FreeformBlock`), точки соединения где угодно на фигуре
  (`ConnectionPoint`), связи со своим цветом/подписью/стилем (`Connector`).
  Программа не навязывает смысл связей — только структурную целостность
  (нельзя сослаться на несуществующий блок).
- **Ссылки в markdown**: `[[page:id]]`, `[[block:id]]`, `[[suggestion:id]]`,
  с необязательным alias `|Текст`. Рендерятся кликабельными через
  `app/static/js/wiki-links.js`, названия резолвятся через
  `POST /api/nodes/resolve-refs`.
- **Предложения** — любой участник может прислать идею и/или патч к любому
  узлу; owner/editor принимает или отклоняет.
- **Авторизация** — Telegram OpenID Connect (Authorization Code + PKCE),
  без паролей.

## Запуск

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # заполнить SECRET_KEY, DATABASE_URL, REDIS_URL, TELEGRAM_*

# PostgreSQL и Redis — установить локально (brew/apt), создать БД:
psql postgres -c "CREATE USER flowforge WITH PASSWORD 'flowforge';"
psql postgres -c "CREATE DATABASE flowforge OWNER flowforge;"

export FLASK_APP=wsgi.py
flask db init
flask db migrate -m "init"
flask db upgrade

python run.py   # http://localhost:5000
```

Telegram-бот: `@BotFather` → выбрать бота → Bot Settings → Web Login →
**Switch to OpenID Connect Login** (необратимо) → указать
`http://localhost:5000/auth/telegram/callback` как redirect URI → получить
Client ID/Secret в `.env`.

## Структура

```
app/models/       User, Project, Node, FreeformDiagram/Block/ConnectionPoint/Connector, Suggestion
app/services/      graph_validator.py (патчи диаграммы), page_patch.py (патчи страниц),
                   realtime.py (WebSocket+Redis), i18n.py
app/routes/        auth.py (Telegram OIDC), projects.py, nodes.py (дерево+патчи),
                   suggestions.py, main.py (одна страница editor.html)
app/static/js/     tree-nav.js (дерево), canvas-graph.js (SVG-рендер),
                   canvas.js (drag/связи), canvas-socket.js, wiki-links.js,
                   editor.js (точка сборки), project-panel.js, api-client.js, i18n.js
translations/      ru.json, uk.json, en.json — общий набор ключей, ни одного
                   текста не зашито в .py/.js напрямую
```
