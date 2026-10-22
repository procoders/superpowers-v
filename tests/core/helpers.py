from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True


def sh(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True).stdout


def write(repo, files):
    for name, content in files.items():
        p = Path(repo) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def make_repo(tmp, files=None, commit=True):
    repo = Path(tmp) / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    sh(repo, "init", "-q")
    for k, v in (("user.name", "Test"), ("user.email", "test@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", os.devnull)):
        sh(repo, "config", k, v)
    write(repo, files or {})
    if commit:
        sh(repo, "add", "-A")
        sh(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return repo


def commit_all(repo, msg="change"):
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "--allow-empty", "-m", msg)


def key_path(repo) -> Path:
    return Path(repo).resolve() / ".git/compound-v/receipt.key"


def cli(repo, *args, stdin=None, env=None):
    full = dict(os.environ, HOME=str(Path(repo).parent / "home"), **(env or {}))
    return subprocess.run([sys.executable, str(SCRIPTS / "compound-v.py"), *args],
                          cwd=str(repo), capture_output=True, text=True, input=stdin, env=full)
