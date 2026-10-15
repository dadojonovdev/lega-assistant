"""Агент: Claude + инструменты для работы с vault."""
import asyncio
import json

SYSTEM = """Ты — AI Operations Manager Далерчона: продакт-менеджера IT-компании, которая делает программные продукты для производителей окон и дверей. Общаешься с ним в Telegram.

Правила:
- Отвечай по-русски, коротко и по делу. Без длинных вступлений.
- Опирайся на заметки его vault (инструменты search_vault, read_note, list_notes). Для вопросов о его проектах, решениях, людях, планах сначала ищи в vault. Называй источник: имя заметки.
- Не выдумывай факты: клиентов, цифры, сроки, бюджет. Если в vault нет ответа, так и скажи: «не определено» или «в vault этого нет».
- Различай: факт из заметки, гипотеза, твоя рекомендация.
- Сохраняй заметку (save_note) только когда он просит запомнить, записать или сохранить, либо прямо диктует заметку. Если он сообщает новый факт или решение без просьбы, предложи сохранить и жди «да». Сохранять можно только в raw/notes или raw/projects; wiki не трогай.
- В этой версии у тебя нет доступа к Jira, Confluence, календарю и личным чатам, и ты ничего не создаёшь во внешних системах. Если просят, скажи, что это будет позже.
- Не раскрывай токены, ключи и персональные данные.
- Знания по-прежнему принадлежат ему: ничего не удаляй и не перезаписывай."""

TOOLS = [
    {
        "name": "search_vault",
        "description": "Поиск по заметкам vault по ключевым словам. Возвращает пути и фрагменты.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "read_note",
        "description": "Прочитать заметку по относительному пути, например wiki/projects/plan-pervyh-90-dnej.md.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "list_notes",
        "description": "Показать содержимое папки vault (пустой путь = корень).",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "save_note",
        "description": "Создать новую заметку (compiled: false). Не перезаписывает существующие. folder: raw/notes или raw/projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "folder": {"type": "string", "enum": ["raw/notes", "raw/projects"]},
            },
            "required": ["title", "body"],
        },
    },
]


def dispatch_tool(vault, name: str, args: dict) -> str:
    try:
        if name == "search_vault":
            return json.dumps(vault.search(args.get("query", "")), ensure_ascii=False)
        if name == "read_note":
            return vault.read(args.get("path", ""))
        if name == "list_notes":
            return json.dumps(vault.list_dir(args.get("path", "")), ensure_ascii=False)
        if name == "save_note":
            rel = vault.save_note(args.get("title", ""), args.get("body", ""), args.get("folder", "raw/notes"))
            return f"Сохранено: {rel}"
        return f"Неизвестный инструмент: {name}"
    except Exception as e:  # ошибка инструмента возвращается модели, не роняет бота
        return f"Ошибка: {e}"


async def run_agent(client, model: str, vault, history: list, user_text: str, max_steps: int = 6) -> str:
    messages = list(history) + [{"role": "user", "content": user_text}]
    text_out = ""
    for _ in range(max_steps):
        resp = await client.messages.create(
            model=model, max_tokens=1500, system=SYSTEM, tools=TOOLS, messages=messages,
        )
        blocks = [b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content]
        text_out = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if resp.stop_reason != "tool_use":
            return text_out or "Готово."
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for b in blocks:
            if b.get("type") == "tool_use":
                out = await asyncio.to_thread(dispatch_tool, vault, b["name"], b.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": out[:12000]})
        messages.append({"role": "user", "content": results})
    return text_out or "Не удалось завершить за отведённое число шагов; уточни запрос."
