"""
Read-only exploration of a cloned repository on disk.
All paths are relative to ``repo_root`` and normalized to prevent traversal outside the tree.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

MAX_READ_LINES = 150
MAX_LIST_ENTRIES = 250
SUMMARY_HEAD_LINES = 50
SKIP_DIR_NAMES = {
    ".git",
    "docs",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
}


def _safe_rel_path(repo_root: Path, rel: str) -> Path:
    root = repo_root.resolve()
    candidate = (root / rel.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes repository root") from exc
    return candidate


def list_files(repo_root: str | os.PathLike[str], path: str = ".") -> dict:
    """
    List files and directories under ``path`` (relative to repo root), recursively,
    skipping common generated/vendor directories. Caps at MAX_LIST_ENTRIES entries.
    """
    root = Path(repo_root).resolve()
    try:
        base = _safe_rel_path(root, path or ".")
    except ValueError as exc:
        return {"error": str(exc), "entries": []}
    if not base.exists():
        return {"error": f"path not found: {path!r}", "entries": []}
    if not base.is_dir():
        return {"error": f"not a directory: {path!r}", "entries": []}

    entries: list[str] = []

    def walk(current: Path, depth: int) -> None:
        if len(entries) >= MAX_LIST_ENTRIES:
            return
        if depth > 12:
            return
        try:
            for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if len(entries) >= MAX_LIST_ENTRIES:
                    return
                rel = str(child.relative_to(root)).replace("\\", "/")
                if child.is_dir():
                    if child.name in SKIP_DIR_NAMES or child.name.startswith("."):
                        continue
                    entries.append(rel + "/")
                    walk(child, depth + 1)
                else:
                    if child.name.startswith("."):
                        continue
                    entries.append(rel)
        except PermissionError:
            entries.append(f"# permission denied: {current}")

    walk(base, 0)
    truncated = len(entries) >= MAX_LIST_ENTRIES
    return {"path": path, "entries": entries, "truncated": truncated}


def read_file(repo_root: str | os.PathLike[str], path: str) -> dict:
    """
    Return file contents with 1-based line numbers, at most MAX_READ_LINES lines.
    """
    root = Path(repo_root).resolve()
    try:
        target = _safe_rel_path(root, path)
    except ValueError as exc:
        return {"error": str(exc), "content": ""}
    if not target.exists() or not target.is_file():
        return {"error": f"file not found: {path!r}", "content": ""}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": str(exc), "content": ""}

    lines = text.splitlines()
    total = len(lines)
    chunk = lines[:MAX_READ_LINES]
    numbered = "\n".join(f"{i + 1:6d}|{line}" for i, line in enumerate(chunk))
    return {
        "path": path,
        "total_lines": total,
        "truncated": total > MAX_READ_LINES,
        "content": numbered,
    }


def search_code(repo_root: str | os.PathLike[str], query: str) -> dict:
    """
    Simple substring / glob search across text files under the repository.
    ``query`` supports ``*`` wildcards (matched with fnmatch on the line).
    """
    if not query or not query.strip():
        return {"error": "empty query", "matches": []}

    root = Path(repo_root).resolve()
    raw = query.strip()
    use_glob = "*" in raw or "?" in raw
    pattern_re = re.compile(re.escape(raw)) if not use_glob else None
    matches: list[dict] = []
    max_matches = 45

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for name in filenames:
            if len(matches) >= max_matches:
                break
            if name.startswith("."):
                continue
            ext = Path(name).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz", ".exe", ".dll", ".so", ".bin"}:
                continue
            file_path = Path(dirpath) / name
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                if len(matches) >= max_matches:
                    break
                ok = fnmatch.fnmatch(line, raw) if use_glob else bool(pattern_re and pattern_re.search(line))
                if ok:
                    preview = line.strip()[:160]
                    matches.append({"file": rel, "line": lineno, "text": preview})
        if len(matches) >= max_matches:
            break

    return {"query": query, "matches": matches, "truncated": len(matches) >= max_matches}


def get_file_summary(repo_root: str | os.PathLike[str], path: str) -> dict:
    """
    Lightweight summary: line count, size, and the first SUMMARY_HEAD_LINES lines (no numbering).
    """
    root = Path(repo_root).resolve()
    try:
        target = _safe_rel_path(root, path)
    except ValueError as exc:
        return {"error": str(exc)}
    if not target.exists() or not target.is_file():
        return {"error": f"file not found: {path!r}"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": str(exc)}
    lines = text.splitlines()
    head = "\n".join(lines[:SUMMARY_HEAD_LINES])
    return {
        "path": path,
        "line_count": len(lines),
        "byte_size": target.stat().st_size,
        "head": head,
        "head_truncated": len(lines) > SUMMARY_HEAD_LINES,
    }
