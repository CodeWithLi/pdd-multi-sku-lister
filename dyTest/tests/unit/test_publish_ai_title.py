"""publish_ai_title 单元测试。"""

from dy_agent.skills.listing.publish_ai_title import (
    _read_title_from_input,
    wait_and_apply_page_ai_title,
)


class _FakeLocator:
    def __init__(self, *, count: int = 0, value: str = "", attr_value: str = ""):
        self._count = count
        self._value = value
        self._attr_value = attr_value

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def input_value(self, timeout=0):
        return self._value

    def get_attribute(self, name: str):
        return self._attr_value


class _FakePage:
    def __init__(self, *, evaluate_result: str = ""):
        self._evaluate_result = evaluate_result

    def locator(self, selector: str):
        return _FakeLocator()

    def evaluate(self, script: str):
        return self._evaluate_result

    def get_by_text(self, *args, **kwargs):
        return _FakeLocator()


def test_read_title_from_input_via_evaluate():
    page = _FakePage(evaluate_result="简约ins卡皮巴拉抽绳笔袋学生高颜值大容量可爱多层文")
    assert _read_title_from_input(page) == "简约ins卡皮巴拉抽绳笔袋学生高颜值大容量可爱多层文"


def test_wait_and_apply_page_ai_title_skips_wait_when_prefilled(monkeypatch):
    page = _FakePage(evaluate_result="已有标题内容足够长")
    slept = []

    def fake_sleep(sec):
        slept.append(sec)

    monkeypatch.setattr("dy_agent.skills.listing.publish_ai_title.time.sleep", fake_sleep)
    title = wait_and_apply_page_ai_title(
        page,
        "acc",
        "unit",
        initial_wait=15,
        max_wait=30,
    )
    assert title == "已有标题内容足够长"
    assert slept == []
