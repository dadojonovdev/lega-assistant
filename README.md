# AI Operations Manager — Telegram-бот (v0)

Что умеет: отвечает по заметкам vault (поиск, чтение), сохраняет новые заметки в `raw/notes` или `raw/projects` с `compiled: false`, синхронизирует vault через закрытый git-репозиторий. Не создаёт ничего во внешних системах, к Jira, Confluence, календарю и личным чатам не подключён.

Безопасность: отвечает только одному пользователю (`ALLOWED_TELEGRAM_USER_ID`) и только в личном чате; сохраняет только в `raw/notes` и `raw/projects`; существующие файлы не перезаписывает; не читает вне vault и служебные папки; токены в логах скрываются; есть дневной лимит сообщений.

## Запуск на Railway
1. Репозиторий с этим кодом (закрытый) и репозиторий с vault (закрытый).
2. Токен бота: в Telegram открыть @BotFather, команда `/newbot`.
3. Ключ API Claude (отдельный от подписки на Claude): console.anthropic.com → API keys.
4. Токен GitHub (fine-grained): доступ только к репозиторию vault, право Contents: Read and write.
5. На Railway: новый сервис из репозитория с кодом; переменные из `.env.example` задать в настройках сервиса (не в коде и не в чате).
6. Подключить том (volume) на `/data`, чтобы vault не клонировался заново при каждом деплое.
7. Написать боту `/myid`, скопировать число в `ALLOWED_TELEGRAM_USER_ID`, дождаться перезапуска.

## Команды
`/note текст` — сохранить заметку; `/sync` — подтянуть vault; любой текст — вопрос ассистенту; `/myid` — показать свой ID.

## Локальная проверка
`python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python test_local.py`

## Режим ПК (без API-ключа)
Бот запускается на Windows-ПК и отвечает через Claude Code (`claude -p`) по подписке.
1. Установи Python 3.12 и Claude Code, один раз войди: `claude` → /login.
2. Скопируй `.env.pc.example` в `.env`, впиши токен бота; `ALLOWED_TELEGRAM_USER_ID` впишешь после `/myid`.
3. Запусти `start.bat`. ПК должен быть включён. Два экземпляра с одним токеном (ПК и Railway) одновременно работать не могут.
