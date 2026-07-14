"""catalog selector parsing tests."""

from pathlib import Path

from dy_agent.skills.listing.catalog import (
    is_image_set_dir,
    list_local_listing_targets,
    parse_listing_target_product_selector,
    parse_listing_target_selector,
    resolve_listing_units,
)
from dy_agent.core.config import YamlSettings


def test_is_image_set_dir():
    assert is_image_set_dir("第一套")
    assert is_image_set_dir("第2套图")
    assert not is_image_set_dir("BD046A")


def test_parse_listing_target_selector():
    assert parse_listing_target_selector("BD046/第一套") == ("BD046", "第一套")
    assert parse_listing_target_selector("BD046/BD046A") is None


def test_parse_listing_target_product_selector():
    assert parse_listing_target_product_selector("BD046/第一套/BD046A") == (
        "BD046",
        "第一套",
        "BD046A",
    )


def test_list_local_listing_targets(tmp_path: Path):
    family = tmp_path / "BD046"
    set_dir = family / "第一套"
    product_dir = set_dir / "BD046A"
    product_dir.mkdir(parents=True)
    (product_dir / "1.png").write_bytes(b"x")

    targets = list_local_listing_targets(tmp_path)
    assert len(targets) == 1
    assert targets[0]["selector"] == "BD046/第一套"
    assert targets[0]["product_codes"] == ["BD046A"]


def test_resolve_listing_units_by_set_selector(tmp_path: Path):
    family = tmp_path / "BD046"
    set_dir = family / "第一套"
    for code in ("BD046A", "BD046B"):
        product_dir = set_dir / code
        product_dir.mkdir(parents=True)
        (product_dir / "1.png").write_bytes(b"x")
        (product_dir / f"{code}+M1.png").write_bytes(b"x")

    settings = YamlSettings()
    units = resolve_listing_units(["BD046/第一套"], settings, assets_root=tmp_path)
    assert len(units) == 2
    assert {u.product_code for u in units} == {"BD046A", "BD046B"}
