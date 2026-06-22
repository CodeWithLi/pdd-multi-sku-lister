from __future__ import annotations

from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PipelineIntegrationConfig,
    excel_fallback_enabled,
    save_pipeline_excel_fallback_to_config,
)


def test_excel_fallback_enabled_reads_pipeline_flag():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pipeline=PipelineIntegrationConfig(excel_fallback_enabled=True),
    )
    assert excel_fallback_enabled(cfg) is True

    cfg_off = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pipeline=PipelineIntegrationConfig(excel_fallback_enabled=False),
    )
    assert excel_fallback_enabled(cfg_off) is False


def test_save_pipeline_excel_fallback_to_config(tmp_path):
    path = tmp_path / "feishu.yaml"
    path.write_text("app_id: x\napp_secret: y\nbitable_app_token: z\n", encoding="utf-8")
    save_pipeline_excel_fallback_to_config(True, path=path)
    text = path.read_text(encoding="utf-8")
    assert "excel_fallback_enabled: true" in text
