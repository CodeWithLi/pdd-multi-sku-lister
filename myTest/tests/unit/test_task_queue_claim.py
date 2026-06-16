"""任务队列 claim 逻辑单元测试。"""

from pdd_agent.db.repositories import _busy_account_ids_for_claim


class _FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _FakeSession:
    def __init__(self, running_accounts, paused_accounts):
        self._running_accounts = running_accounts
        self._paused_accounts = paused_accounts
        self._call = 0

    def scalars(self, _stmt):
        self._call += 1
        if self._call == 1:
            return _FakeScalarResult(self._running_accounts)
        return _FakeScalarResult(self._paused_accounts)


def test_busy_account_ids_merge_running_and_paused():
    session = _FakeSession(["store_A", "store_B"], ["store_B", "store_C"])
    assert _busy_account_ids_for_claim(session) == {"store_A", "store_B", "store_C"}


def test_busy_account_ids_ignore_empty_account_id():
    session = _FakeSession(["store_A", ""], [""])
    assert _busy_account_ids_for_claim(session) == {"store_A"}
