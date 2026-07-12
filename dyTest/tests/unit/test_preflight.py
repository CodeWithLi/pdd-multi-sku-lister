"""preflight 单元测试。"""

from pathlib import Path

from dy_agent.core.config import YamlSettings
from dy_agent.skills.listing.preflight import run_preflight


def test_preflight_missing_assets_root(tmp_path: Path):
    settings = YamlSettings()
    settings.paths.assets_root = str(tmp_path / "nonexistent")
    report = run_preflight(["BD046A"], settings)
    assert not report.ok
    assert any(i.reason_code == "assets_root_missing" for i in report.issues)


def test_preflight_product_not_found(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    settings = YamlSettings()
    settings.paths.assets_root = str(assets)
    report = run_preflight(["BD999Z"], settings, assets_root=assets)
    assert not report.ok
    assert any(i.reason_code == "product_dir_missing" for i in report.issues)
