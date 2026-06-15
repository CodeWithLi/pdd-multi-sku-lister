"""run_cancel 单元测试。"""

from pdd_agent.api.services.run_cancel import clear_cancel, is_cancelled, request_cancel


def test_run_cancel_request_and_check():
    rid = "test-run-cancel-001"
    clear_cancel(rid)
    assert not is_cancelled(rid)
    request_cancel(rid)
    assert is_cancelled(rid)
    clear_cancel(rid)
    assert not is_cancelled(rid)
