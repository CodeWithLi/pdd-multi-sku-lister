from pdd_agent.integrations.feishu import feishu_async_dispatch


def test_schedule_feishu_push_in_background_starts_daemon_thread(monkeypatch):
    created: list[dict] = []

    class FakeThread:
        def __init__(self, target, kwargs, name, daemon):
            created.append(
                {"target": target, "kwargs": kwargs, "name": name, "daemon": daemon, "started": False}
            )

        def start(self):
            created[0]["started"] = True

    monkeypatch.setattr(feishu_async_dispatch.threading, "Thread", FakeThread)

    def worker(**kwargs):
        return kwargs

    feishu_async_dispatch.schedule_feishu_push_in_background(
        worker,
        thread_name="feishu-test",
        kwargs={"success": False, "account_id": "store_A"},
    )

    assert len(created) == 1
    assert created[0]["target"] is worker
    assert created[0]["kwargs"] == {"success": False, "account_id": "store_A"}
    assert created[0]["name"] == "feishu-test"
    assert created[0]["daemon"] is True
    assert created[0]["started"] is True
