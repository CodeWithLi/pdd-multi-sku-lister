from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.integrations.minio.config import (
    load_minio_config,
    minio_rabbitmq_enabled,
    minio_refresh_mode,
)


def _env(*, minio_enabled=None, rabbitmq_enabled=None):
    return SimpleNamespace(
        minio_enabled=minio_enabled,
        minio_endpoint="",
        minio_access_key="",
        minio_secret_key="",
        minio_bucket="",
        rabbitmq_enabled=rabbitmq_enabled,
        rabbitmq_username="",
        rabbitmq_password="",
        alist_url="",
        alist_username="",
        alist_password="",
    )


def test_env_flags_override_enabled_yaml_values(tmp_path):
    cfg_path = tmp_path / "minio.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "enabled: true",
                "endpoint: 127.0.0.1:9000",
                "access_key: key",
                "secret_key: secret",
                "bucket: images",
                "refresh_mode: rabbitmq",
                "rabbitmq:",
                "  enabled: true",
            ]
        ),
        encoding="utf-8",
    )

    with patch(
        "pdd_agent.integrations.minio.config.get_minio_env_settings",
        return_value=_env(minio_enabled=False, rabbitmq_enabled=False),
    ):
        cfg = load_minio_config(cfg_path)

    assert cfg.enabled is False
    assert cfg.rabbitmq.enabled is False
    assert minio_refresh_mode(cfg) == "poll"
    assert minio_rabbitmq_enabled(cfg) is False


def test_unset_env_flags_preserve_yaml_values(tmp_path):
    cfg_path = tmp_path / "minio.yaml"
    cfg_path.write_text(
        "enabled: true\nrefresh_mode: rabbitmq\nrabbitmq:\n  enabled: true\n",
        encoding="utf-8",
    )

    with patch(
        "pdd_agent.integrations.minio.config.get_minio_env_settings",
        return_value=_env(),
    ):
        cfg = load_minio_config(cfg_path)

    assert cfg.enabled is True
    assert cfg.rabbitmq.enabled is True
    assert minio_refresh_mode(cfg) == "rabbitmq"
