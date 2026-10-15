"""Работа с vault: git-синхронизация, поиск, чтение, безопасное создание заметок."""
import os
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

ALLOWED_SAVE_DIRS = ("raw/notes", "raw/projects")
SKIP_DIRS = {".git", ".obsidian", "node_modules"}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "ғ": "g", "ӣ": "i", "қ": "q",
    "ӯ": "u", "ҳ": "h", "ҷ": "j",
}


def slugify(text: str, max_len: int = 50) -> str:
    out = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum()):
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return (slug[:max_len].strip("-")) or "note"


def redact(text: str) -> str:
    return re.sub(r"(https://[^:@/\s]+:)[^@\s]+(@)", r"\1***\2", text or "")


class Vault:
    def __init__(self, path, repo: str | None = None, token: str | None = None,
                 author_name="AI Operations Manager", author_email="assistant@localhost",
                 tz_hours: int = 5, use_git: bool = True):
        self.path = Path(path)
        self.repo = repo
        self.token = token
        self.author_name = author_name
        self.author_email = author_email
        self.tz = timezone(timedelta(hours=tz_hours))
        self.lock = threading.Lock()
        self.has_remote = False
        self.use_git = use_git

    # ---- git ----
    def _git(self, *args, check=True):
        res = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(redact(f"git {' '.join(args[:2])}: {res.stderr.strip() or res.stdout.strip()}"))
        return res

    def _remote_url(self):
        if not self.repo:
            return None
        if self.repo.startswith(("http://", "https://", "/", "file://")) or os.path.isabs(self.repo):
            return self.repo
        if self.token:
            return f"https://x-access-token:{self.token}@github.com/{self.repo}.git"
        return f"https://github.com/{self.repo}.git"

    def setup(self):
        with self.lock:
            if not self.use_git:
                if not self.path.is_dir():
                    raise RuntimeError(f"Папка vault не найдена: {self.path}")
                return
            url = self._remote_url()
            if url and not (self.path / ".git").exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                res = subprocess.run(["git", "clone", url, str(self.path)], capture_output=True, text=True)
                if res.returncode != 0:
                    raise RuntimeError(redact(f"git clone: {res.stderr.strip()}"))
            elif not (self.path / ".git").exists():
                self.path.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", str(self.path)], capture_output=True, text=True, check=True)
            self._git("config", "user.name", self.author_name)
            self._git("config", "user.email", self.author_email)
            self.has_remote = bool(self._git("remote", check=False).stdout.strip())

    def pull(self):
        with self.lock:
            self._pull_unlocked()

    def _pull_unlocked(self):
        if not self.has_remote:
            return
        # на пустом удалённом репозитории тянуть нечего
        if self._git("rev-parse", "--verify", "HEAD", check=False).returncode != 0 and \
           not self._git("ls-remote", "--heads", "origin", check=False).stdout.strip():
            return
        self._git("pull", "--rebase", "--autostash", check=False)

    # ---- чтение ----
    def _iter_md(self):
        for root, dirs, files in os.walk(self.path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".md"):
                    yield Path(root) / f

    def _safe(self, rel: str) -> Path:
        p = (self.path / rel).resolve()
        if self.path.resolve() not in p.parents and p != self.path.resolve():
            raise ValueError("Путь вне vault")
        if any(part in SKIP_DIRS for part in p.relative_to(self.path.resolve()).parts):
            raise ValueError("Служебная папка недоступна")
        return p

    def search(self, query: str, limit: int = 8):
        def stem(t):  # грубая основа слова: русские окончания не мешают поиску
            return t if len(t) <= 4 else t[: max(4, len(t) - 2)]
        terms = [stem(t) for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        if not terms:
            return []
        results = []
        for p in self._iter_md():
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            if score == 0:
                continue
            idx = min((low.find(t) for t in terms if t in low), default=0)
            snippet = text[max(0, idx - 80): idx + 220].replace("\n", " ")
            results.append((score, str(p.relative_to(self.path)), snippet))
        results.sort(key=lambda r: -r[0])
        return [{"path": r[1], "score": r[0], "snippet": r[2]} for r in results[:limit]]

    def read(self, rel: str, max_chars: int = 12000) -> str:
        p = self._safe(rel)
        if p.suffix != ".md" or not p.is_file():
            raise ValueError("Нет такой заметки (.md)")
        text = p.read_text(encoding="utf-8")
        return text[:max_chars] + ("\n…[обрезано]" if len(text) > max_chars else "")

    def list_dir(self, rel: str = "", limit: int = 100):
        p = self._safe(rel) if rel else self.path.resolve()
        if not p.is_dir():
            raise ValueError("Нет такой папки")
        items = []
        for c in sorted(p.iterdir()):
            if c.name in SKIP_DIRS:
                continue
            items.append(c.name + ("/" if c.is_dir() else ""))
        return items[:limit]

    # ---- запись ----
    def save_note(self, title: str, body: str, folder: str = "raw/notes", source: str = "telegram") -> str:
        folder = folder.strip("/")
        if folder not in ALLOWED_SAVE_DIRS:
            raise ValueError(f"Сохранять можно только в: {', '.join(ALLOWED_SAVE_DIRS)}")
        title = (title or "").strip() or "Заметка"
        now = datetime.now(self.tz)
        fname = f"{now:%Y-%m-%d-%H%M}-{slugify(title)}.md"
        with self.lock:
            self._pull_unlocked()
            d = self.path / folder
            d.mkdir(parents=True, exist_ok=True)
            target = d / fname
            n = 2
            while target.exists():  # ничего не перезаписываем
                target = d / f"{target.stem.rsplit('-v', 1)[0]}-v{n}.md"
                n += 1
            safe_title = title.replace('"', "'")
            content = (
                "---\n"
                "compiled: false\n"
                "type: note\n"
                f"source: {source}\n"
                f"source_date: {now:%Y-%m-%d}\n"
                f'title: "{safe_title}"\n'
                "---\n\n"
                f"# {title}\n\n{body.strip()}\n"
            )
            target.write_text(content, encoding="utf-8")
            rel = str(target.relative_to(self.path))
            if not self.use_git:
                return rel
            self._git("add", rel)
            self._git("commit", "-m", f"note: {title[:60]}")
            pushed = self._push_unlocked()
            return rel + ("" if pushed else " (сохранена локально, push не выполнен)")

    def _push_unlocked(self) -> bool:
        if not self.has_remote:
            return False
        for _ in range(3):
            res = self._git("push", "-u", "origin", "HEAD", check=False)
            if res.returncode == 0:
                return True
            self._git("pull", "--rebase", "--autostash", check=False)
        return False
