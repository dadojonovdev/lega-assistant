"""Режим «без API-ключа»: ответы даёт Claude Code на этом же ПК (по подписке пользователя).
Claude Code запускается в папке vault и сам читает заметки. Запись в vault ему запрещена."""
import asyncio
import os
import shutil

SYSTEM = """Ты — AI Operations Manager Далерчона: продакт-менеджера IT-компании, которая делает ПО для производителей окон и дверей. Общаешься с ним в Telegram.
Рабочая папка — его vault (Obsidian). Сначала читай wiki/INDEX.md, затем нужные заметки (Grep/Glob/Read).
- Отвечай по-русски, коротко и по делу, без длинных вступлений. Называй источник: имя заметки.
- Не выдумывай факты (клиентов, цифры, сроки, бюджет). Нет ответа в vault — так и скажи: «не определено» / «в vault этого нет».
- Различай: факт из заметки, гипотеза, твоя рекомендация.
- Файлы ты не меняешь. Если просят что-то запомнить, скажи использовать команду /note текст.
- Нет доступа к Jira, Confluence, календарю и личным чатам; во внешних системах ничего не создавай.
- Не раскрывай токены, ключи и персональные данные."""

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "240"))


async def run_cli(vault_dir: str, history: list, text: str, model: str | None = None) -> str:
    ctx = "\n".join(
        f"{'Пользователь' if h['role'] == 'user' else 'Ассистент'}: {h['content']}" for h in history
    )
    prompt = (f"Предыдущий диалог:\n{ctx}\n\n" if ctx else "") + f"Новое сообщение пользователя:\n{text}"
    cmd = [CLAUDE_BIN, "-p", prompt, "--append-system-prompt", SYSTEM,
           "--allowedTools", "Read", "Glob", "Grep",
           "--disallowedTools", "Bash", "Write", "Edit", "WebFetch", "WebSearch"]
    if model:
        cmd += ["--model", model]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=vault_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return "Claude Code не ответил вовремя. Попробуй короче или позже."
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: {err.decode('utf-8', 'ignore')[:300]}")
    return out.decode("utf-8", "ignore").strip()
