"""整合链路 — 分批上架单元测试。"""

from pdd_agent.api.services.pipeline_listing_throttle import (
    build_listing_throttle_state,
    group_selectors_by_image_set,
    split_selectors_into_set_batches,
)


def test_group_selectors_by_image_set_preserves_order():
    selectors = [
        "BD713/第一套/BD713A",
        "BD713/第一套/BD713B",
        "BD720/第一套图/BD720A",
    ]
    groups = group_selectors_by_image_set(selectors)
    assert [key for key, _ in groups] == ["BD713/第一套", "BD720/第一套图"]
    assert groups[0][1] == ["BD713/第一套/BD713A", "BD713/第一套/BD713B"]


def test_split_selectors_into_set_batches():
    selectors = [
        "BD713/第一套/BD713A",
        "BD713/第一套/BD713B",
        "BD720/第一套图/BD720A",
        "BD720/第一套图/BD720B",
        "BD800/第二套/BD800A",
    ]
    batches = split_selectors_into_set_batches(selectors, batch_set_count=2)
    assert len(batches) == 2
    assert batches[0] == [
        "BD713/第一套/BD713A",
        "BD713/第一套/BD713B",
        "BD720/第一套图/BD720A",
        "BD720/第一套图/BD720B",
    ]
    assert batches[1] == ["BD800/第二套/BD800A"]


def test_build_listing_throttle_state_disabled_or_single_batch():
    selectors = ["BD713/第一套/BD713A", "BD713/第一套/BD713B"]
    assert build_listing_throttle_state(
        selectors,
        enabled=False,
        batch_set_count=1,
        interval_minutes=30,
        listing_payload_base={},
    ) is None
    assert build_listing_throttle_state(
        selectors,
        enabled=True,
        batch_set_count=5,
        interval_minutes=30,
        listing_payload_base={},
    ) is None


def test_build_listing_throttle_state_multi_batch():
    selectors = [
        "BD713/第一套/BD713A",
        "BD720/第一套图/BD720A",
        "BD800/第二套/BD800A",
    ]
    state = build_listing_throttle_state(
        selectors,
        enabled=True,
        batch_set_count=1,
        interval_minutes=15,
        listing_payload_base={"category_keyword": "玩偶"},
    )
    assert state is not None
    assert state["total_sets"] == 3
    assert state["total_batches"] == 3
    assert state["interval_minutes"] == 15
    assert state["batches"][0] == ["BD713/第一套/BD713A"]
