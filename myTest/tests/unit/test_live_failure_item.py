from pdd_agent.api.services.failure_workbench import resolve_failure_item_status


def test_resolve_failure_item_status_retryable():
    status, retryable = resolve_failure_item_status("validation_errors")
    assert status == "retryable"
    assert retryable is True


def test_resolve_failure_item_status_rejected():
    status, retryable = resolve_failure_item_status("rejected_after_publish")
    assert status == "failed"
    assert retryable is False


def test_resolve_failure_item_status_uncertain():
    status, retryable = resolve_failure_item_status("submit_uncertain")
    assert status == "submit_uncertain"
    assert retryable is True
