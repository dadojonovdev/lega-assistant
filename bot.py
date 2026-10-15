"""Telegram-бот AI Operations Manager (v0): заметки в vault и ответы по vault."""
import asyncio
import logging
import os
from collections import defaultdict, deque
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from cli_agent import run_cli
from vault import Vault, redact

def _load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("assistant")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # пусто = режим Claude Code на ПК (подписка)
MODEL = os.environ.get("MODEL") or None
ALLOWED = os.environ.get("ALLOWED_TELEGRAM_USER_ID", "").strip()
DAILY_CAP = int(os.environ.get("DAILY_MESSAGE_CAP", "200"))
VAULT_DIR = os.environ.get("VAULT_DIR", "/data/vault")
VAULT_REPO = os.environ.get("VAULT_REPO") or None
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or None
TZ_HOURS = int(os.environ.get("TZ_OFFSET_HOURS", "5"))

history = defaultdict(lambda: deque(maxlen=12))
usage = {"day": date.today(), "n": 0}
dp = Dispatcher()
vault: Vault


def authorized(m: Message) -> bool:
    return bool(ALLOWED) and m.from_user is not None and str(m.from_user.id) == ALLOWED \
        and m.chat.type == "private"


async def reply_long(m: Message, text: str):
    text = text or "Готово."
    for i in range(0, len(text), 4000):
        await m.answer(text[i:i + 4000])


@dp.message(Command("myid"))
async def cmd_myid(m: Message):
    await m.answer(f"Твой Telegram ID: {m.from_user.id}\nЗадай его в переменной ALLOWED_TELEGRAM_USER_ID.")


@dp.message(Command("start"))
async def cmd_start(m: Message):
    if not authorized(m):
        await m.answer("Бот не настроен для этого пользователя. /myid покажет твой ID.")
        return
    await m.answer(
        "Привет. Я AI Operations Manager.\n"
        "• Пиши вопросы — отвечу по vault.\n"
        "• /note текст — сохранить заметку в raw/notes.\n"
        "• /sync — подтянуть свежую версию vault."
    )


@dp.message(Command("note"))
async def cmd_note(m: Message):
    if not authorized(m):
        return
    body = (m.text or "").partition(" ")[2].strip()
    if not body:
        await m.answer("Напиши: /note текст заметки")
        return
    title = body.splitlines()[0][:60]
    try:
        rel = await asyncio.to_thread(vault.save_note, title, body)
        await m.answer(f"Сохранено: {rel}")
    except Exception as e:
        log.error("save failed: %s", redact(str(e)))
        await m.answer(f"Не удалось сохранить: {redact(str(e))[:300]}")


@dp.message(Command("sync"))
async def cmd_sync(m: Message):
    if not authorized(m):
        return
    try:
        await asyncio.to_thread(vault.pull)
        n = len(list(vault._iter_md()))
        await m.answer(f"vault обновлён, заметок: {n}")
    except Exception as e:
        await m.answer(f"Ошибка синхронизации: {redact(str(e))[:300]}")


@dp.message(F.text)
async def on_text(m: Message):
    if not authorized(m):
        if not ALLOWED:
            await m.answer(f"Бот ещё не настроен. Твой ID: {m.from_user.id}. Задай его в ALLOWED_TELEGRAM_USER_ID.")
        return
    if usage["day"] != date.today():
        usage.update(day=date.today(), n=0)
    if usage["n"] >= DAILY_CAP:
        await m.answer("Дневной лимит сообщений исчерпан.")
        return
    usage["n"] += 1
    await m.bot.send_chat_action(m.chat.id, "typing")
    try:
        await asyncio.to_thread(vault.pull)
        h = history[m.chat.id]
        if API_KEY:
            from agent import run_agent
            answer = await run_agent(client, MODEL or "claude-sonnet-5-5", vault, list(h), m.text[:4000])
        else:
            answer = await run_cli(str(vault.path), list(h), m.text[:4000], MODEL)
        h.append({"role": "user", "content": m.text[:4000]})
        h.append({"role": "assistant", "content": answer})
        await reply_long(m, answer)
    except Exception as e:
        log.error("agent error: %s", redact(str(e)))
        await m.answer(f"Ошибка при обработке: {redact(str(e))[:350]}")


async def main():
    global vault, client
    missing = [k for k, v in {"TELEGRAM_BOT_TOKEN": BOT_TOKEN}.items() if not v]
    if missing:
        raise SystemExit(f"Не заданы переменные: {', '.join(missing)}")
    use_git = os.environ.get("VAULT_GIT", "1") != "0"
    vault = Vault(VAULT_DIR, repo=VAULT_REPO, token=GITHUB_TOKEN, tz_hours=TZ_HOURS, use_git=use_git)
    await asyncio.to_thread(vault.setup)
    log.info("vault готов: %s, удалённый репозиторий: %s", VAULT_DIR, vault.has_remote)
    if API_KEY:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=API_KEY)
    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("бот запущен, ограничение по пользователю: %s", "да" if ALLOWED else "НЕТ (задай ALLOWED_TELEGRAM_USER_ID)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
