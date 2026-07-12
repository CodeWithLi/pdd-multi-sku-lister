"""运行环境配置（prod / test 双实例）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pdd_agent.core import config as config_module
from pdd_agent.core.config import (
    background_jobs_enabled,
    get_runtime_profile,
    resolve_env_file,
)


@pytest.fixture(autouse=True)
def _clear_env_cache():
    config_module.get_env_settings.cache_clear()
    yield
    config_module.get_env_settings.cache_clear()


def test_resolve_env_file_default(monkeypatch):
    monkeypatch.delenv("PDD_ENV_FILE", raising=False)
    assert resolve_env_file().endswith(".env")


def test_resolve_env_file_override(monkeypatch, tmp_path: Path):
    custom = tmp_path / "custom.env"
    custom.write_text("PDD_RUNTIME_PROFILE=test\n", encoding="utf-8")
    monkeypatch.setenv("PDD_ENV_FILE", str(custom))
    assert resolve_env_file() == str(custom)


def test_runtime_profile_from_env_file(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "\n".join(
            [
                "PDD_RUNTIME_PROFILE=test",
                "PDD_BACKGROUND_JOBS=false",
                "DATABASE_URL=mysql+pymysql://u:p@127.0.0.1:3306/pdd_agent_platform_test?charset=utf8mb4",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PDD_ENV_FILE", str(env_file))
    monkeypatch.delenv("PDD_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("PDD_BACKGROUND_JOBS", raising=False)

    assert get_runtime_profile() == "test"
    assert background_jobs_enabled() is False


def test_background_jobs_default_true(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("PDD_RUNTIME_PROFILE=prod\n", encoding="utf-8")
    monkeypatch.setenv("PDD_ENV_FILE", str(env_file))
    monkeypatch.delenv("PDD_BACKGROUND_JOBS", raising=False)

    assert background_jobs_enabled() is True
