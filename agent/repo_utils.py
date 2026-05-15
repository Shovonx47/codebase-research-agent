"""Clone or resolve a repository to a local path for code tools."""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from git import Repo

from agent.models import Repository


def _is_remote(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith("http://") or u.startswith("https://") or u.startswith("git@")


def ensure_local_copy(repo: Repository) -> Path:
    """
    Resolve ``repo.url`` to a directory on disk: clone remotes under REPOS_DIR,
    or validate and use a local filesystem path.
    """
    repos_dir = Path(settings.REPOS_DIR)
    repos_dir.mkdir(parents=True, exist_ok=True)

    raw = repo.url.strip()
    if not _is_remote(raw):
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Local repository path does not exist or is not a directory: {path}")
        repo.local_path = str(path)
        repo.save(update_fields=["local_path", "updated_at"])
        return path

    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    target = repos_dir / key
    if (target / ".git").is_dir():
        r = Repo(target)
        try:
            r.remotes.origin.pull()
        except Exception:
            pass
    else:
        Repo.clone_from(raw, target)

    repo.local_path = str(target.resolve())
    repo.save(update_fields=["local_path", "updated_at"])
    return Path(repo.local_path)
