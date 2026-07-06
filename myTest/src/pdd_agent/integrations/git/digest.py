"""采集指定日期的 Git 提交记录。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pdd_agent.paths import PROJECT_ROOT

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    TZ = timezone(timedelta(hours=8))
_COMMIT_MARKER = "===COMMIT==="


class GitDigestError(Exception):
    """Git 采集失败。"""


@dataclass
class GitCommitRecord:
    full_hash: str
    short_hash: str
    author: str
    committed_at: str
    subject: str
    body: str
    files: list[dict[str, int | str]] = field(default_factory=list)


def resolve_git_repo_path(explicit: str = "") -> Path:
    """解析 Git 仓库根目录；默认探测 PROJECT_ROOT 及其上一级。"""
    text = str(explicit or os.getenv("GIT_REPO_PATH", "")).strip()
    if text:
        path = Path(text).expanduser().resolve()
        if not (path / ".git").exists():
            raise GitDigestError(f"指定路径不是 Git 仓库: {path}")
        return path

    for candidate in (PROJECT_ROOT.parent, PROJECT_ROOT):
        if (candidate / ".git").exists():
            return candidate.resolve()
    raise GitDigestError("未找到 Git 仓库，请配置 git_repo_path 或 GIT_REPO_PATH")


def _run_git(repo_path: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitDigestError("未安装 git 命令") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise GitDigestError(stderr or "git 命令执行失败")
    return proc.stdout


def today_in_tz() -> date:
    return datetime.now(TZ).date()


def _since_arg(day: date) -> str:
    return f"{day.isoformat()} 00:00:00 +0800"


def _parse_commit_blocks(raw: str) -> list[GitCommitRecord]:
    blocks = [b.strip() for b in raw.split(_COMMIT_MARKER) if b.strip()]
    commits: list[GitCommitRecord] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 5:
            continue
        full_hash, short_hash, author, committed_at, subject = lines[:5]
        body_lines = lines[5:]
        body = "\n".join(body_lines).strip()
        # git %B 常重复 subject 为首行，去掉重复标题
        if body.startswith(subject):
            body = body[len(subject) :].lstrip("\n").strip()
        commits.append(
            GitCommitRecord(
                full_hash=full_hash.strip(),
                short_hash=short_hash.strip(),
                author=author.strip(),
                committed_at=committed_at.strip(),
                subject=subject.strip(),
                body=body,
            )
        )
    return commits


def _attach_file_stats(repo_path: Path, commits: list[GitCommitRecord]) -> None:
    for commit in commits:
        raw = _run_git(
            repo_path,
            "show",
            "--numstat",
            "--format=",
            commit.full_hash,
        )
        files: list[dict[str, int | str]] = []
        for line in raw.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            add_text, delete_text, path = parts
            if add_text == "-" or delete_text == "-":
                continue
            files.append(
                {
                    "path": path.strip(),
                    "add": int(add_text),
                    "delete": int(delete_text),
                }
            )
        commit.files = files


def collect_commits_for_day(
    *,
    repo_path: str | Path | None = None,
    day: date | None = None,
    include_file_stats: bool = True,
) -> list[GitCommitRecord]:
    """采集某一天（默认今天，Asia/Shanghai）的全部提交。"""
    path = Path(repo_path).resolve() if repo_path else resolve_git_repo_path()
    target_day = day or today_in_tz()
    raw = _run_git(
        path,
        "log",
        f"--since={_since_arg(target_day)}",
        f"--until={(target_day.isoformat())} 23:59:59 +0800",
        "--pretty=format:===COMMIT===%n%H%n%h%n%an%n%ai%n%s%n%B",
        "--no-merges",
    )
    commits = _parse_commit_blocks(raw)
    if include_file_stats and commits:
        _attach_file_stats(path, commits)
    return commits


def commits_to_context(commits: list[GitCommitRecord]) -> str:
    """将提交列表整理为 LLM 可读的纯文本上下文。"""
    if not commits:
        return "（今日无 Git 提交）"

    chunks: list[str] = []
    for idx, commit in enumerate(commits, start=1):
        file_lines = []
        for item in commit.files[:30]:
            file_lines.append(
                f"  - {item['path']} (+{item['add']}/-{item['delete']})"
            )
        if len(commit.files) > 30:
            file_lines.append(f"  - ... 另有 {len(commit.files) - 30} 个文件")

        parts = [
            f"提交 {idx}",
            f"时间: {commit.committed_at}",
            f"作者: {commit.author}",
            f"标题: {commit.subject}",
        ]
        if commit.body:
            parts.append(f"说明:\n{commit.body}")
        if file_lines:
            parts.append("变更文件:\n" + "\n".join(file_lines))
        chunks.append("\n".join(parts))
    return "\n\n".join(chunks)
