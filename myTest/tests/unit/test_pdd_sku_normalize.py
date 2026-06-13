from pdd_agent.skills.published.pdd_sku_normalize import normalize_pdd_lookup_sku, split_spec_code


def test_split_spec_code_single():
    assert split_spec_code("BD630D") == ("BD630D", "")


def test_split_spec_code_combo():
    assert split_spec_code("BD630D+YKL001A") == ("BD630D", "YKL001A")


def test_normalize_pdd_lookup_sku():
    sku = normalize_pdd_lookup_sku(
        {
            "style_name": "蓝色慕斯星星笔袋",
            "package_name": "单件装：包包【爆款热销】",
            "inventory": "298",
            "activity_price": "12.80",
            "group_price": "13.80",
            "single_price": "50.00",
            "spec_code": "BD630D+YKL001A",
        }
    )
    assert sku["style_code"] == "BD630D"
    assert sku["model_code"] == "YKL001A"
    assert sku["combo_folder"] == "BD630D+YKL001A"
    assert sku["group_price"] == "13.80"
