"""槽位对齐试验模块测试。"""

from pathlib import Path

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import parse_listing_target
from pdd_agent.skills.listing.listing_spec_pipeline import apply_unit_listing_specs


def test_slot_alignment_bd720_five_sizes_not_six():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings, slot_alignment_test=False)
    unit = next(u for u in units if u.product_code == "BD720A")

    apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=True)
    assert len(unit.model_codes) == 5
    assert "笔袋+挂件(公仔)" not in unit.model_codes
    assert len(unit.skus) == 10

    b_combo = next(s for s in unit.skus if s.combo_folder == "BD720B+GJ318B")
    a_gj = next(s for s in unit.skus if s.combo_folder == "BD720A+GJ82A")
    assert b_combo.model_name == a_gj.model_name == "笔袋+公仔"


def test_slot_alignment_disabled_keeps_legacy_union():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings, slot_alignment_test=False)
    unit = next(u for u in units if u.product_code == "BD720A")

    apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=False)
    assert len(unit.model_codes) == 6
    assert "笔袋+挂件(公仔)" in unit.model_codes


def test_slot_alignment_pipeline_noop_when_flag_off():
    settings = load_yaml_settings()
    units = parse_listing_target("BD720/第一套图/BD720A", settings)
    unit = next(u for u in units if u.product_code == "BD720A")
    before = list(unit.model_codes)

    errors = apply_unit_listing_specs(unit, allow_ai=False, slot_alignment_test=False)
    assert errors == []
    assert unit.model_codes == before or len(unit.model_codes) == 6
