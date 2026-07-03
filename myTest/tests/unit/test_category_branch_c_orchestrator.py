"""分支 C 页面形态分类器 + 编排层契约测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.skills.listing.category_branch_c_orchestrator import (
    ensure_branch_c_category_selection,
)
from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
    META_KEY_CATEGORY_AI_APPLIED,
    ensure_branch_c_category_ready_for_ai_title_flow,
)
from pdd_agent.skills.listing.category_branch_c_variant import (
    BranchCPageVariant,
    classify_branch_c_page_variant,
)


def test_classify_traditional_when_on_page():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": True, "pathReady": False},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_variant.branch_c_is_simplified_ai_title_context",
        return_value=False,
    ):
        assert (
            classify_branch_c_page_variant(page, {"title_mode": "page_ai"})
            == BranchCPageVariant.TRADITIONAL
        )


def test_classify_simplified_auto_only_when_path_ready():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": False, "pathReady": True},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_variant.branch_c_is_simplified_ai_title_context",
        return_value=True,
    ):
        assert (
            classify_branch_c_page_variant(page, {"title_mode": "page_ai"})
            == BranchCPageVariant.SIMPLIFIED_AUTO
        )


def test_classify_pending_when_title_filled_but_category_not_ready():
    """回归：标题已填但分类区未渲染时不得判为 AUTO。"""
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": False, "pathReady": False, "blocking": False},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_variant.branch_c_is_simplified_ai_title_context",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_needs_titled_manual_category_pick",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.read_branch_c_titled_manual_state",
        return_value={
            "selectButtonVisible": False,
            "modalOpen": False,
            "noRecommendation": False,
        },
    ), patch(
        "pdd_agent.skills.listing.upload._category_page_needs_manual_selection",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.upload._category_section_is_ready",
        return_value=False,
    ):
        assert (
            classify_branch_c_page_variant(page, {"title_mode": "page_ai"})
            == BranchCPageVariant.SIMPLIFIED_PENDING
        )


def test_classify_manual_when_select_button_and_no_recommendation():
    page = MagicMock()
    with patch(
        "pdd_agent.skills.listing.category_branch_c_recent.read_branch_c_category_selection_state",
        return_value={"onPage": False, "pathReady": False},
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_recent.branch_c_category_path_ready_strict",
        return_value=False,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_variant.branch_c_is_simplified_ai_title_context",
        return_value=True,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_titled_picker.branch_c_needs_titled_manual_category_pick",
        return_value=True,
    ):
        assert (
            classify_branch_c_page_variant(page, {"title_mode": "page_ai"})
            == BranchCPageVariant.SIMPLIFIED_MANUAL
        )


def test_orchestrator_simplified_auto_skips_selection():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.log_branch_c_variant_diagnostics",
        return_value=BranchCPageVariant.SIMPLIFIED_AUTO,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._run_strategy_simplified_auto",
        return_value=True,
    ) as auto:
        ok, variant = ensure_branch_c_category_selection(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    assert variant == "simplified_auto"
    auto.assert_called_once()


def test_orchestrator_pending_waits_then_manual():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    variants = iter(
        [
            BranchCPageVariant.SIMPLIFIED_PENDING,
            BranchCPageVariant.SIMPLIFIED_MANUAL,
        ]
    )
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.log_branch_c_variant_diagnostics",
        side_effect=lambda *a, **k: next(variants),
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._wait_simplified_category_render",
    ) as wait_render, patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._run_strategy_simplified_manual",
        return_value=True,
    ) as manual:
        ok, variant = ensure_branch_c_category_selection(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    assert variant == "simplified_manual"
    wait_render.assert_called_once()
    manual.assert_called_once()


def test_orchestrator_traditional_calls_recent_path():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.log_branch_c_variant_diagnostics",
        return_value=BranchCPageVariant.TRADITIONAL,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._run_strategy_traditional",
        return_value=True,
    ) as traditional:
        ok, variant = ensure_branch_c_category_selection(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    assert variant == "traditional"
    traditional.assert_called_once()


def test_orchestrator_manual_never_calls_auto_skip():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.log_branch_c_variant_diagnostics",
        return_value=BranchCPageVariant.SIMPLIFIED_MANUAL,
    ), patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._run_strategy_simplified_auto",
    ) as auto, patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator._run_strategy_simplified_manual",
        return_value=True,
    ) as manual:
        ok, _ = ensure_branch_c_category_selection(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    auto.assert_not_called()
    manual.assert_called_once()


def test_legacy_gate_delegates_to_orchestrator():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.ensure_branch_c_category_selection",
        return_value=(True, "simplified_auto"),
    ) as orch:
        ok = ensure_branch_c_category_ready_for_ai_title_flow(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    orch.assert_called_once()


def test_simplified_auto_sets_meta_via_orchestrator():
    page = MagicMock()
    listing_info = {"title_mode": "page_ai"}
    with patch(
        "pdd_agent.skills.listing.category_branch_c_orchestrator.log_branch_c_variant_diagnostics",
        return_value=BranchCPageVariant.SIMPLIFIED_AUTO,
    ):
        ok, _ = ensure_branch_c_category_selection(
            page, "store", "label", listing_info, "笔袋"
        )
    assert ok is True
    assert listing_info[META_KEY_CATEGORY_AI_APPLIED] is True
