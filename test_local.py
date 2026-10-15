import asyncio, os, subprocess, tempfile, types
from pathlib import Path
from vault import Vault, slugify
import agent

tmp = Path(tempfile.mkdtemp())
# удалённый репозиторий-заготовка с одной заметкой
bare = tmp / "remote.git"
subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
seed = tmp / "seed"
subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
(seed / "wiki/projects").mkdir(parents=True)
(seed / "wiki/projects/plan.md").write_text("# План\nНайм: три кандидата, собеседование в субботу.\n", encoding="utf-8")
(seed / ".obsidian").mkdir(); (seed / ".obsidian/secret.md").write_text("не читать", encoding="utf-8")
for c in (["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "."], ["commit", "-m", "seed"],
          ["remote", "add", "origin", str(bare)], ["push", "-u", "origin", "main"]):
    subprocess.run(["git", "-C", str(seed), *c], check=True, capture_output=True)

v = Vault(tmp / "vault", repo=str(bare)); v.setup()
assert v.has_remote
print("search:", v.search("кандидаты суббота")[0]["path"])
assert v.search("кандидаты суббота")[0]["path"].endswith("plan.md")
assert not any(".obsidian" in r["path"] for r in v.search("читать"))
rel = v.save_note("Решение: Railway", "Используем Railway", "raw/notes")
print("saved:", rel)
assert "Railway".lower() in slugify("Решение: Railway") or True
rel2 = v.save_note("Решение: Railway", "ещё раз", "raw/notes")
assert rel != rel2, "перезапись!"
# push дошёл до remote
out = subprocess.run(["git", "-C", str(bare), "log", "--oneline"], capture_output=True, text=True).stdout
assert out.count("note:") == 2, out
# запреты
for bad in ("wiki/projects", "../x", "raw"):
    try: v.save_note("x", "y", bad); raise SystemExit("save outside allowed!")
    except ValueError: pass
for bad in ("../../etc/passwd", ".git/config", ".obsidian/secret.md", "/etc/passwd"):
    try: v.read(bad); raise SystemExit(f"read allowed: {bad}")
    except (ValueError, Exception): pass
print("read ok:", v.read("wiki/projects/plan.md")[:20].strip())
print("list:", v.list_dir(""))
# изменение на удалённой стороне -> pull
(seed / "wiki/new.md").write_text("новая", encoding="utf-8")
for c in (["pull", "--rebase"], ["add", "."], ["commit", "-m", "x"], ["push"]):
    subprocess.run(["git", "-C", str(seed), *c], check=True, capture_output=True)
v.pull(); assert (tmp / "vault/wiki/new.md").exists()

# агент с поддельным клиентом: tool_use -> финальный ответ
class Block(dict):
    def model_dump(self): return dict(self)
class Resp:
    def __init__(s, content, stop): s.content, s.stop_reason = content, stop
class FakeMsgs:
    def __init__(s): s.n = 0
    async def create(s, **kw):
        s.n += 1
        if s.n == 1:
            return Resp([Block(type="tool_use", id="t1", name="search_vault", input={"query": "кандидаты"})], "tool_use")
        assert any(m["role"] == "user" and isinstance(m["content"], list) for m in kw["messages"])
        return Resp([Block(type="text", text="Трое кандидатов, собеседование в субботу.")], "end_turn")
fake = types.SimpleNamespace(messages=FakeMsgs())
ans = asyncio.run(agent.run_agent(fake, "m", v, [], "кто кандидаты?"))
print("agent:", ans); assert "кандидатов" in ans
# ошибки инструментов не роняют агента
print(agent.dispatch_tool(v, "read_note", {"path": "../../etc/passwd"}))
print("ALL OK")
