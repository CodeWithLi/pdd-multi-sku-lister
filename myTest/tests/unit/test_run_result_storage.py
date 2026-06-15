from pdd_agent.api.services.task_runner import (
    _compact_run_result_for_storage,
    _summarize_listing_message,
)


def test_summarize_listing_message_short():
    result = {
        "results": [
            {"listing_label": "BD713A/第一套图", "status": "success"},
            {"listing_label": "BD716A/第一套图", "status": "retryable", "reason": "preview_not_ready"},
        ]
    }
    msg = _summarize_listing_message(result)
    assert "共2个单元" in msg
    assert "成功1" in msg
    assert "可重试1" in msg
    assert "BD716A" in msg
    assert len(msg) < 500


def test_compact_run_result_truncates_row_text():
    huge = "x" * 50000
    result = {
        "results": [
            {
                "listing_label": "BD713A/第一套图",
                "pdd_product_matched_row_text": huge,
            }
        ]
    }
    compacted = _compact_run_result_for_storage(result)
    row_text = compacted["results"][0]["pdd_product_matched_row_text"]
    assert len(row_text) < 600
    assert "共50000字" in row_text
