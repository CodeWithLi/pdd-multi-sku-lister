"""Streamlit：批量下架页（由 app.py 挂载）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from pdd_auto.delist.time_utils import parse_threshold, format_datetime


def _default_delist_settings() -> dict:
    return {
        "min_created_after": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dry_run": True,
        "merchant_code_contains": "",
        "max_delist_per_run": 20,
        "account_ids": [],
    }


def render_delist_tab(
    cfg: dict,
    save_config,
    run_subprocess,
    is_proc_running,
    read_log,
    render_log_html,
    delist_log: Path,
):
    st.subheader("批量下架")
    st.caption(
        "进入商家后台「商品列表 → 在售中」，自动**翻页**扫描；仅对**创建时间严格晚于**门槛的商品下架。"
        "可多选店铺按顺序执行。达到单店条数上限即停；若已扫到早于门槛的商品页也会提前停止，避免无限翻页。"
    )

    ds = cfg.setdefault("delist_settings", _default_delist_settings())
    accounts = cfg.get("accounts") or []
    all_ids = [a.get("account_id") for a in accounts if a.get("account_id")]

    st.warning(
        "误下架风险极高：请先用「试运行」核对日志，确认只会命中新上架商品后再关闭试运行。"
    )

    c1, c2 = st.columns(2)
    with c1:
        threshold_str = st.text_input(
            "最早可下架创建时间（严格大于此时间才下架）",
            value=ds.get("min_created_after", ""),
            help="示例：2026-06-04 14:00:00。创建时间 **等于** 该时刻的商品也不会下架。",
            key="delist_threshold",
        )
        ds["min_created_after"] = threshold_str.strip()

        try:
            th = parse_threshold(ds["min_created_after"])
            st.success(f"当前门槛解析为：{format_datetime(th)}（仅晚于此时间的商品可下架）")
        except ValueError as e:
            st.error(str(e))

    with c2:
        ds["dry_run"] = st.toggle(
            "试运行（只扫描，不点击下架）",
            value=bool(ds.get("dry_run", True)),
            key="delist_dry_run",
        )
        ds["max_delist_per_run"] = st.number_input(
            "单店单次最多处理条数",
            min_value=1,
            max_value=999,
            value=int(ds.get("max_delist_per_run", 20)),
            help="跨页累计。达到此数量即停；若翻页后整页商品创建时间均已早于门槛，也会提前停止（不会扫完全部 960 条）。",
            key="delist_max",
        )
        ds["merchant_code_contains"] = st.text_input(
            "商家编码包含（可选，留空不限制）",
            value=ds.get("merchant_code_contains", ""),
            help="若填写，仅下架行内文本包含该片段的商品，用于进一步缩小范围。",
            key="delist_code_filter",
        )

    st.markdown("**参与下架的店铺**")
    saved_ids = ds.get("account_ids") or []
    default_sel = [i for i in all_ids if i in saved_ids] if saved_ids else [
        a.get("account_id") for a in accounts if a.get("enabled") and a.get("account_id")
    ]
    selected = st.multiselect(
        "选择店铺（可多选，将按顺序逐个处理）",
        options=all_ids,
        default=default_sel,
        key="delist_accounts",
    )
    ds["account_ids"] = selected

    confirm = st.checkbox(
        "我已确认：仅会下架创建时间晚于上述门槛的商品，并已理解试运行与正式执行的区别",
        key="delist_confirm",
    )

    st.divider()
    b1, b2, b3 = st.columns([1, 1, 2])

    with b1:
        if st.button("保存下架配置", use_container_width=True, key="delist_save_cfg"):
            save_config(cfg)
            st.success("下架配置已写入 config.json")

    with b2:
        proc_key = "delist_proc"
        if not is_proc_running(proc_key):
            start_disabled = not confirm or not selected or not threshold_str.strip()
            if st.button(
                "开始下架",
                type="primary",
                use_container_width=True,
                disabled=start_disabled,
                key="delist_start",
            ):
                try:
                    parse_threshold(threshold_str)
                except ValueError as e:
                    st.error(str(e))
                else:
                    save_config(cfg)
                    st.session_state[proc_key] = run_subprocess("delist_main.py", delist_log)
                    st.rerun()
        else:
            if st.button("停止下架任务", type="secondary", use_container_width=True, key="delist_stop"):
                p = st.session_state.get(proc_key)
                if p:
                    p.terminate()
                st.session_state[proc_key] = None
                st.rerun()

    with b3:
        if is_proc_running("delist_proc"):
            st.info("下架任务运行中，请查看下方日志")
        else:
            p = st.session_state.get("delist_proc")
            if p is not None:
                code = p.poll()
                if code == 0:
                    st.success("上次下架任务正常结束")
                elif code is not None:
                    st.error(f"上次下架任务异常退出（返回码: {code}）")

    st.markdown("**下架日志**")
    log_text = read_log(delist_log)
    if log_text.strip():
        st.markdown(render_log_html(log_text), unsafe_allow_html=True)
        with st.expander("原始文本"):
            st.code(log_text, language=None)
    else:
        st.info("暂无下架日志。保存配置后点击「开始下架」。")

    if is_proc_running("delist_proc"):
        import time

        time.sleep(2)
        st.rerun()
