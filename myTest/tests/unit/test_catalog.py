"""catalog Skill 单元测试（无需浏览器）。"""

import pytest

from pdd_agent.skills.listing.catalog import is_image_set_dir, list_image_sets


def test_image_set_pattern():
    """套图目录名匹配规则。"""
    assert is_image_set_dir("第一套图")
    assert is_image_set_dir("第二套图")
    assert not is_image_set_dir("BD046A")
    assert not is_image_set_dir("主图")


def test_list_image_sets_empty(tmp_path):
    """商品目录不存在时返回空列表。"""
    assert list_image_sets("BD999", tmp_path) == []
