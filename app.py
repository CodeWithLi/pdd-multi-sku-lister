import streamlit as st
import subprocess
import sys
import json
import re
import copy
import time
import os
import threading
from pathlib import Path

from pdd_auto.log_utils import decode_subprocess_chunk, sanitize_log_text
from pdd_auto.paths import CONFIG_PATH, LOG_DIR
from pdd_auto.ui.delist_tab import render_delist_tab
from pdd_auto.products.multi_spec.catalog import (
    list_image_sets,
    list_products as list_multi_spec_products,
)
from pdd_auto.products.assets import (
    DEFAULT_VARIANT,
    build_product_relative_path,
    list_categories,
    list_product_codes,
    list_sku_images,
    list_variants,
    migrate_account_product_fields,
    resolve_account_product_abs_path,
    resolve_account_product_path,
    validate_product_images,
    load_asset_rules,
)

st.set_page_config(
    page_title="PDD 上架管理系统",
    page_icon="🛍️",
    layout="wide",
)

MAIN_LOG = LOG_DIR / "current_run.txt"
AI_LOG = LOG_DIR / "ai_run.txt"
DELIST_LOG = LOG_DIR / "delist_run.txt"


# ─── 通用工具 ───────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for acc in cfg.get("accounts", []):
        acc["product"] = migrate_account_product_fields(acc, cfg)
    return cfg


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def read_log(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return ""
    text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        text = raw.decode("gbk", errors="ignore")
    return sanitize_log_text(text)


def _drain_subprocess_output(proc: subprocess.Popen, log_file: Path):
    """后台读取子进程输出，过滤二进制乱码后写入日志文件。"""
    try:
        with open(log_file, "wb") as f:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                cleaned = decode_subprocess_chunk(chunk)
                if cleaned:
                    f.write(cleaned.encode("utf-8"))
                    f.flush()
    except Exception:
        pass


def run_subprocess(script: str, log_file: Path, extra_args: list = None) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if os.name == "nt":
        env["CHROME_LOG_FILE"] = "NUL"
    else:
        env["CHROME_LOG_FILE"] = "/dev/null"
    args = [sys.executable, "-u", script] + (extra_args or [])
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(Path(__file__).parent),
    )
    threading.Thread(
        target=_drain_subprocess_output,
        args=(proc, log_file),
        daemon=True,
    ).start()
    return proc


def is_proc_running(key: str) -> bool:
    p = st.session_state.get(key)
    return p is not None and p.poll() is None


# ─── 日志渲染 ───────────────────────────────────────────────────────────────

def render_log_html(text: str) -> str:
    """将 print 日志逐行着色，返回可 unsafe_allow_html 渲染的 HTML。"""
    lines = text.split("\n") if text.strip() else ["等待任务启动..."]
    parts = []
    for line in lines:
        if "❌" in line:
            style = "color:#b71c1c;background:#ffebee"
        elif "⚠️" in line:
            style = "color:#e65100;background:#fff8e1"
        elif "🎉" in line or ("✅" in line and "完毕" in line):
            style = "color:#1b5e20;background:#e8f5e9;font-weight:600"
        elif "✅" in line:
            style = "color:#2e7d32;background:#f1f8e9"
        elif line.startswith("---") or line.startswith("\n---"):
            style = "color:#1565c0;font-weight:600"
        else:
            style = "color:#333"
        safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(
            f'<div style="{style};padding:1px 8px;font-family:monospace;font-size:13px;white-space:pre-wrap">'
            f'{safe}</div>'
        )
    return (
        '<div style="border:1px solid #e0e0e0;border-radius:6px;padding:8px;'
        'height:520px;overflow-y:auto;background:#fafafa">'
        + "".join(parts)
        + "</div>"
    )


# ─── 统计解析 ───────────────────────────────────────────────────────────────

def parse_stats(log_text: str) -> dict:
    """解析 print 日志，返回 {account_id: {status, last_msg, lines}} 字典。"""
    accounts = {}
    for raw_line in log_text.split("\n"):
        line = raw_line.strip()
        m = re.match(r"[-\s]*\[(\w+)\]", line)
        if not m:
            continue
        acc_id = m.group(1)
        if acc_id.upper() in ("AI",):
            continue

        entry = accounts.setdefault(acc_id, {"status": "pending", "last_msg": "", "lines": 0})
        entry["lines"] += 1
        entry["last_msg"] = line

        if "正在检查登录状态" in line or "开始执行" in line:
            if entry["status"] == "pending":
                entry["status"] = "running"
        if "🎉 成功标志" in line or "上架完毕" in line:
            entry["status"] = "success"
        elif "❌ 业务运行报错" in line or "❌ 登录超时" in line or "❌ 登录检查" in line or "❌ 未配置" in line:
            entry["status"] = "failed"
        elif "⚠️ 异常提醒" in line:
            entry["status"] = "warning"
        elif "⚠️ 未找到主图资源" in line:
            entry["status"] = "skipped"

    return accounts


STATUS_ICON = {
    "success": "✅",
    "failed": "❌",
    "warning": "⚠️",
    "running": "🔄",
    "skipped": "⏭️",
    "pending": "⏳",
}
STATUS_COLOR = {
    "success": "#e8f5e9",
    "failed": "#ffebee",
    "warning": "#fff8e1",
    "running": "#e3f2fd",
    "skipped": "#f3e5f5",
    "pending": "#fafafa",
}


def new_empty_sku() -> dict:
    return {
        "spec_name": "",
        "sku_image": "",
        "group_price": "",
        "single_price": "",
        "inventory": "10",
        "sku_code": "",
    }


def clone_skus(skus: list) -> list:
    return copy.deepcopy(skus or [])


def sku_widget_prefix(acc_idx: int) -> str:
    rev = st.session_state.get("sku_widget_rev", 0)
    return f"sku_{acc_idx}_{rev}"


def bump_sku_widget_keys():
    st.session_state.sku_widget_rev = st.session_state.get("sku_widget_rev", 0) + 1


def open_sku_editor(acc_idx: int):
    """从 config.json 加载草稿；未点保存前不会写入 cfg。"""
    fresh = load_config()
    st.session_state.sku_draft = clone_skus(fresh["accounts"][acc_idx].get("skus"))
    st.session_state.sku_draft_acc_idx = acc_idx
    st.session_state.sku_editor_idx = acc_idx
    bump_sku_widget_keys()


def close_sku_editor():
    st.session_state.sku_editor_idx = None
    st.session_state.sku_draft = None
    st.session_state.sku_draft_acc_idx = None
    bump_sku_widget_keys()


def ensure_sku_draft(cfg: dict, acc_idx: int) -> list:
    if (
        st.session_state.get("sku_draft_acc_idx") != acc_idx
        or st.session_state.get("sku_draft") is None
    ):
        open_sku_editor(acc_idx)
    return st.session_state.sku_draft


def sync_sku_draft_from_session(acc_idx: int, draft: list):
    prefix = sku_widget_prefix(acc_idx)
    fields = [
        ("spec_name", "spec"),
        ("sku_image", "img"),
        ("group_price", "gp"),
        ("single_price", "sp"),
        ("inventory", "inv"),
        ("sku_code", "code"),
    ]
    for j in range(len(draft)):
        for field, suffix in fields:
            key = f"{prefix}_{j}_{suffix}"
            if key in st.session_state:
                val = st.session_state[key]
                if field == "sku_image" and isinstance(val, str):
                    draft[j][field] = val.strip()
                else:
                    draft[j][field] = val


def sku_image_path(account: dict, filename: str, cfg: dict | None = None) -> Path | None:
    if not filename:
        return None
    try:
        folder = resolve_account_product_abs_path(account, cfg or st.session_state.get("cfg"))
    except ValueError:
        return None
    path = folder / filename.strip()
    return path if path.is_file() else None


def sync_account_skus_from_session(cfg: dict, acc_idx: int):
    """兼容旧调用：同步草稿。"""
    draft = ensure_sku_draft(cfg, acc_idx)
    sync_sku_draft_from_session(acc_idx, draft)


def validate_image_for_sku(
    filename: str,
    account: dict,
    draft: list,
    row_idx: int,
    strict: bool,
    cfg: dict | None = None,
) -> tuple[bool, str]:
    """
    校验预览图是否可用。
    硬性：文件必须在当前素材目录内。
    严格模式：须 sku_ 开头，且不能被其他 SKU 行占用。
    """
    name = (filename or "").strip()
    if not name:
        return False, "未填写预览图文件"

    try:
        folder = resolve_account_product_abs_path(account, cfg or st.session_state.get("cfg"))
    except ValueError as e:
        return False, str(e)
    if not folder.is_dir():
        return False, f"素材目录不存在"
    if not (folder / name).is_file():
        return False, f"图片不在当前素材目录：`{name}`"

    if strict:
        if not name.startswith("sku_"):
            return False, f"严格模式下只能使用 sku_ 开头的图片（当前：`{name}`）"
        for i, sku in enumerate(draft):
            if i == row_idx:
                continue
            used = (sku.get("sku_image") or "").strip()
            if used == name:
                label = (sku.get("spec_name") or "").strip() or f"第 {i + 1} 行"
                return False, f"该图片已被「{label}」使用，不能重复选用"

    return True, ""


def validate_sku_preview_images(
    account: dict,
    skus: list | None = None,
    strict: bool = False,
    cfg: dict | None = None,
) -> tuple[bool, list[str]]:
    """校验每条 SKU 的预览图。"""
    errors = []
    rows = skus if skus is not None else account.get("skus", [])

    for i, sku in enumerate(rows):
        spec = (sku.get("spec_name") or "").strip() or f"第 {i + 1} 行"
        filename = (sku.get("sku_image") or "").strip()
        ok, msg = validate_image_for_sku(filename, account, rows, i, strict, cfg=cfg)
        if not ok:
            errors.append(f"{spec}：{msg}")
    return len(errors) == 0, errors


def _show_sku_validation_errors(errors: list[str], title: str):
    st.error(title)
    for msg in errors:
        st.markdown(f"- {msg}")


def _natural_sort_key(name: str):
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def list_product_images(product_abs: Path, cfg: dict | None = None) -> dict[str, list[str]]:
    """扫描款式文件夹：轮播 1-5、详情 6-8、sku_ 预览图。"""
    rules = load_asset_rules(cfg or st.session_state.get("cfg"))
    ext = rules["ext"]
    groups: dict[str, list[str]] = {"carousel": [], "detail": [], "sku_": [], "其他": []}
    if not product_abs.is_dir():
        return groups
    for i in rules["carousel"]:
        name = f"{i}{ext}"
        if (product_abs / name).is_file():
            groups["carousel"].append(name)
    for i in rules["detail"]:
        name = f"{i}{ext}"
        if (product_abs / name).is_file():
            groups["detail"].append(name)
    groups["sku_"] = list_sku_images(product_abs)
    exts = {".png", ".jpg", ".jpeg"}
    known = set(groups["carousel"] + groups["detail"] + groups["sku_"])
    for f in product_abs.iterdir():
        if f.is_file() and f.suffix.lower() in exts and f.name not in known:
            groups["其他"].append(f.name)
    groups["其他"].sort(key=_natural_sort_key)
    return groups


def _default_multi_spec_codes(ms: dict, products: list[str]) -> list[str]:
    saved = ms.get("product_codes")
    if isinstance(saved, list):
        return [c for c in saved if c in products]
    legacy = (ms.get("product_code") or "").strip()
    return [legacy] if legacy and legacy in products else []


def render_account_multi_spec_config(cfg: dict, acc_idx: int, acc: dict):
    """多规格测试：商品编码多选（SKU 由目录 + Excel 自动解析）。"""
    acc_cfg = cfg["accounts"][acc_idx]
    acc_cfg.setdefault("listing_mode", "multi_spec")
    ms = acc_cfg.setdefault("multi_spec", {})

    st.markdown("**多规格商品**")
    st.caption("素材目录 `多规格测试/` · 可多选商品编码 · 每套图单独上架 · **不选则不发布**")

    products = list_multi_spec_products(cfg)
    if products:
        ms["product_codes"] = st.multiselect(
            "商品编码（可多选）",
            options=products,
            default=_default_multi_spec_codes(ms, products),
            key=f"ms_codes_{acc_idx}",
            help="选哪个上传哪个；每个编码下有几套图就上架几个",
        )
    else:
        raw = st.text_input(
            "商品编码（逗号分隔）",
            value=",".join(ms.get("product_codes") or []),
            key=f"ms_codes_text_{acc_idx}",
            placeholder="BD046A,BD199A",
        )
        ms["product_codes"] = [c.strip() for c in raw.split(",") if c.strip()]

    selected = ms.get("product_codes") or []
    if not selected:
        st.warning("未选择商品编码，该店铺不会发布新商品")
        return

    total_sets = 0
    lines = []
    for pcode in selected:
        sets = [s for s in list_image_sets(pcode, cfg) if s]
        count = len(sets) if sets else 1
        total_sets += count
        if sets:
            lines.append(f"**{pcode}**：{count} 套（{', '.join(sets)}）")
        else:
            lines.append(f"**{pcode}**：1 套（根目录）")
    st.info(f"已选 {len(selected)} 个商品，合计上架 **{total_sets}** 个链接\n\n" + "\n\n".join(lines))


def render_account_product_config(cfg: dict, acc_idx: int, acc: dict):
    """店铺素材：品类 / 商品编码 / 款式。"""
    product = cfg["accounts"][acc_idx].setdefault(
        "product", migrate_account_product_fields(acc, cfg)
    )

    st.markdown("**商品素材**")
    col_cat, col_code = st.columns(2)
    with col_cat:
        existing_cats = list_categories()
        cat_val = product.get("category", "")
        if existing_cats:
            options = existing_cats if cat_val in existing_cats else existing_cats + [cat_val]
            idx = options.index(cat_val) if cat_val in options else 0
            product["category"] = st.selectbox(
                "品类",
                options=options,
                index=idx,
                key=f"prod_cat_{acc_idx}",
            )
        else:
            product["category"] = st.text_input(
                "品类",
                value=cat_val,
                placeholder="挂件",
                key=f"prod_cat_{acc_idx}",
            )
    with col_code:
        codes = list_product_codes(product.get("category", ""))
        code_val = product.get("code", "")
        if codes:
            options = codes if code_val in codes else codes + [code_val]
            idx = options.index(code_val) if code_val in options else 0
            product["code"] = st.selectbox(
                "商品编码",
                options=options,
                index=idx,
                key=f"prod_code_{acc_idx}",
            )
        else:
            product["code"] = st.text_input(
                "商品编码",
                value=code_val,
                placeholder="BCP001",
                key=f"prod_code_{acc_idx}",
            )

    variants = list_variants(product.get("category", ""), product.get("code", ""))
    var_val = product.get("variant") or DEFAULT_VARIANT
    col_var, col_custom = st.columns([1, 1])
    with col_var:
        if variants:
            if var_val not in variants:
                variants = variants + [var_val]
            product["variant"] = st.selectbox(
                "款式",
                options=variants,
                index=variants.index(var_val),
                key=f"prod_var_{acc_idx}",
                help="对应 products/品类/编码/款式 文件夹；单款用 default",
            )
        else:
            product["variant"] = st.text_input(
                "款式",
                value=var_val,
                placeholder=DEFAULT_VARIANT,
                key=f"prod_var_{acc_idx}",
                help="单款固定填 default；多色如 blue、black",
            )
    with col_custom:
        st.caption("路径规则")
        try:
            rel = build_product_relative_path(
                product["category"], product["code"], product["variant"]
            )
            st.code(rel, language=None)
        except ValueError:
            st.caption("请填写品类与编码")

    try:
        rel_path = resolve_account_product_path(acc, cfg)
        abs_path = resolve_account_product_abs_path(acc, cfg)
        ok, errors = validate_product_images(abs_path, cfg)
        if ok:
            st.success(f"素材齐全（1.jpg～8.jpg）· `{rel_path}`")
        elif abs_path.is_dir():
            st.warning(f"素材待补齐 · `{rel_path}`")
            for err in errors[:4]:
                st.caption(f"· {err}")
        else:
            st.info(f"文件夹尚未创建 · `{rel_path}`（设计交付后放置 1.jpg～8.jpg）")
    except ValueError as e:
        st.error(str(e))


@st.dialog("选择预览图", width="large")
def sku_image_picker_dialog(acc_idx: int, row_idx: int):
    cfg = st.session_state.cfg
    acc = cfg["accounts"][acc_idx]
    draft = st.session_state.sku_draft
    try:
        folder = resolve_account_product_abs_path(acc, cfg)
    except ValueError:
        folder = Path(acc.get("product_path", ""))
    spec_name = draft[row_idx].get("spec_name") or f"第 {row_idx + 1} 行"
    prefix = sku_widget_prefix(acc_idx)

    st.caption(f"店铺 **{acc.get('account_id')}** · {spec_name}")
    st.markdown(f"素材目录：`{folder}`")
    strict = st.session_state.get("sku_strict_image", True)
    if strict:
        st.caption("🔒 严格模式：仅可选用 **sku_** 开头、且未被其他 SKU 占用的图片")
    else:
        st.caption("🔓 宽松模式：素材目录内任意图片均可选用")

    if not folder.is_dir():
        st.error("素材目录不存在，请先在控制台配置品类/编码/款式。")
        if st.button("关闭", key=f"pick_close_{acc_idx}_{row_idx}"):
            st.rerun()
        return

    groups = list_product_images(folder, cfg)

    def render_grid(filenames: list[str], tab_key: str):
        if not filenames:
            st.info("该分类下暂无图片")
            return
        per_row = 4
        for start in range(0, len(filenames), per_row):
            row_cols = st.columns(per_row)
            for col_i, fname in enumerate(filenames[start : start + per_row]):
                fpath = folder / fname
                btn_key = f"pick_{acc_idx}_{row_idx}_{tab_key}_{start}_{col_i}"
                used_elsewhere = strict and any(
                    (s.get("sku_image") or "").strip() == fname
                    for k, s in enumerate(draft)
                    if k != row_idx
                )
                with row_cols[col_i]:
                    st.image(str(fpath), use_container_width=True)
                    st.caption(fname)
                    if strict and not fname.startswith("sku_"):
                        st.caption("❌ 非 sku_ 文件")
                    elif used_elsewhere:
                        st.caption("❌ 已被占用")
                    elif st.button("选用", key=btn_key, use_container_width=True):
                        ok, msg = validate_image_for_sku(fname, acc, draft, row_idx, strict, cfg=cfg)
                        if not ok:
                            st.error(msg)
                        else:
                            draft[row_idx]["sku_image"] = fname
                            st.session_state[f"{prefix}_{row_idx}_img"] = fname
                            st.rerun()

    if strict:
        render_grid(groups["sku_"], "sku")
    else:
        tab_sku, tab_carousel, tab_detail, tab_all = st.tabs(
            [
                f"sku_ ({len(groups['sku_'])})",
                f"轮播 1-5 ({len(groups['carousel'])})",
                f"详情 6-8 ({len(groups['detail'])})",
                f"全部 ({sum(len(v) for v in groups.values())})",
            ]
        )
        with tab_sku:
            st.caption("推荐：SKU 预览图通常使用 sku_ 开头的文件")
            render_grid(groups["sku_"], "sku")
        with tab_carousel:
            st.caption("轮播主图 1.jpg～5.jpg（上架时自动上传，此处仅浏览）")
            render_grid(groups["carousel"], "carousel")
        with tab_detail:
            st.caption("详情图 6.jpg～8.jpg（上架时自动上传，此处仅浏览）")
            render_grid(groups["detail"], "detail")
        with tab_all:
            all_files = (
                groups["carousel"]
                + groups["detail"]
                + groups["sku_"]
                + groups["其他"]
            )
            render_grid(all_files, "all")

    if st.button("取消", key=f"pick_cancel_{acc_idx}_{row_idx}"):
        st.rerun()


def render_sku_manager(cfg: dict, acc_idx: int):
    """SKU 配置管理页（草稿编辑，仅保存时写入 config）。"""
    acc = cfg["accounts"][acc_idx]
    acc_id = acc.get("account_id", f"账号{acc_idx}")
    draft = ensure_sku_draft(cfg, acc_idx)
    prefix = sku_widget_prefix(acc_idx)

    top1, top2, top3 = st.columns([1, 2, 3])
    with top1:
        if st.button("← 返回控制台", use_container_width=True):
            close_sku_editor()
            st.rerun()
    with top2:
        st.subheader(f"SKU 配置 · {acc_id}")
    try:
        asset_path = resolve_account_product_path(acc, cfg)
        asset_caption = f"素材目录：`{asset_path}`"
    except ValueError:
        asset_caption = "素材目录：未配置"
    with top3:
        path_col, toggle_col = st.columns([3, 2])
        with path_col:
            st.caption(asset_caption)
        with toggle_col:
            st.session_state.sku_strict_image = st.toggle(
                "SKU 图严格模式",
                value=st.session_state.get("sku_strict_image", True),
                key=f"sku_strict_toggle_{acc_idx}",
                help="启用：仅 sku_ 开头、未占用、且在素材目录内；关闭：素材目录内任意图片",
            )

    strict = st.session_state.get("sku_strict_image", True)
    if strict:
        st.info(
            "当前为编辑草稿 · **严格模式已启用**：预览图须为素材目录下的 **sku_** 文件，且不能与其他 SKU 重复。"
            " 保存后写入 config.json；返回控制台丢弃未保存修改。"
        )
    else:
        st.info(
            "当前为编辑草稿 · **宽松模式**：可选用素材目录内任意图片。"
            " 保存后写入 config.json；返回控制台丢弃未保存修改。"
        )

    if not draft:
        st.warning("暂无 SKU，点击下方「新增 SKU」添加第一条。")
        if st.button("➕ 新增 SKU", type="primary", key=f"sku_add_first_{acc_idx}"):
            draft.append(new_empty_sku())
            bump_sku_widget_keys()
            st.rerun()
        return

    # 表头
    h = st.columns([1, 2, 1.5, 1, 1, 1, 1.5, 0.8])
    headers = ["预览", "规格名称", "预览图文件", "拼单价", "单买价", "库存", "规格编码", "操作"]
    for col, title in zip(h, headers):
        col.markdown(f"**{title}**")
    st.divider()

    delete_idx = None
    for j, sku in enumerate(draft):
        cols = st.columns([1, 2, 1.5, 1, 1, 1, 1.5, 0.8])

        with cols[0]:
            img_path = sku_image_path(acc, sku.get("sku_image", ""), cfg)
            if img_path:
                st.image(str(img_path), width=72)
            else:
                st.markdown(
                    '<div style="width:72px;height:72px;border:1px dashed #888;'
                    'border-radius:6px;display:flex;align-items:center;justify-content:center;'
                    'font-size:11px;color:#888;text-align:center">无预览</div>',
                    unsafe_allow_html=True,
                )
            if st.button(
                "📁 选择图片",
                key=f"sku_pick_{prefix}_{j}",
                use_container_width=True,
                help="从素材目录中选择预览图",
            ):
                sku_image_picker_dialog(acc_idx, j)

        with cols[1]:
            draft[j]["spec_name"] = st.text_input(
                "规格名称",
                value=sku.get("spec_name", ""),
                key=f"{prefix}_{j}_spec",
                label_visibility="collapsed",
            )
        with cols[2]:
            draft[j]["sku_image"] = st.text_input(
                "预览图",
                value=sku.get("sku_image", ""),
                key=f"{prefix}_{j}_img",
                label_visibility="collapsed",
            )
            img_name = (draft[j].get("sku_image") or "").strip()
            if img_name:
                ok, msg = validate_image_for_sku(img_name, acc, draft, j, strict, cfg=cfg)
                if not ok:
                    st.caption(f"⚠️ {msg}")

        with cols[3]:
            draft[j]["group_price"] = st.text_input(
                "拼单价",
                value=sku.get("group_price", ""),
                key=f"{prefix}_{j}_gp",
                label_visibility="collapsed",
            )
        with cols[4]:
            draft[j]["single_price"] = st.text_input(
                "单买价",
                value=sku.get("single_price", ""),
                key=f"{prefix}_{j}_sp",
                label_visibility="collapsed",
            )
        with cols[5]:
            draft[j]["inventory"] = st.text_input(
                "库存",
                value=sku.get("inventory", ""),
                key=f"{prefix}_{j}_inv",
                label_visibility="collapsed",
            )
        with cols[6]:
            draft[j]["sku_code"] = st.text_input(
                "规格编码",
                value=sku.get("sku_code", ""),
                key=f"{prefix}_{j}_code",
                label_visibility="collapsed",
            )
        with cols[7]:
            if st.button("🗑", key=f"sku_del_{prefix}_{j}", help="删除此 SKU"):
                delete_idx = j

        st.divider()

    if delete_idx is not None:
        draft.pop(delete_idx)
        bump_sku_widget_keys()
        st.rerun()

    st.divider()
    bar1, bar2, bar3 = st.columns([1, 1, 3])
    with bar1:
        add_clicked = st.button(
            "➕ 新增 SKU",
            type="primary",
            use_container_width=True,
            key=f"sku_add_{acc_idx}",
        )
    with bar2:
        save_clicked = st.button(
            "💾 保存 SKU 配置",
            use_container_width=True,
            key=f"sku_save_{acc_idx}",
        )
    with bar3:
        st.caption(f"共 {len(draft)} 条（草稿）· 新增前需保证已有 SKU 预览图有效")

    sync_sku_draft_from_session(acc_idx, draft)

    if add_clicked:
        ok, errors = validate_sku_preview_images(acc, draft, strict=strict, cfg=cfg)
        if not ok:
            _show_sku_validation_errors(
                errors,
                "无法新增：请先为当前所有 SKU 配置存在的预览图（可点「📁 选择图片」）",
            )
        else:
            draft.append(new_empty_sku())
            bump_sku_widget_keys()
            st.rerun()

    if save_clicked:
        ok, errors = validate_sku_preview_images(acc, draft, strict=strict, cfg=cfg)
        if not ok:
            _show_sku_validation_errors(errors, "无法保存：以下 SKU 预览图校验未通过")
        else:
            cfg["accounts"][acc_idx]["skus"] = clone_skus(draft)
            save_config(cfg)
            st.session_state.sku_draft = clone_skus(draft)
            st.success("SKU 配置已保存到 config.json")


# ─── Session 初始化 ─────────────────────────────────────────────────────────

if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
if "sku_editor_idx" not in st.session_state:
    st.session_state.sku_editor_idx = None
if "sku_draft" not in st.session_state:
    st.session_state.sku_draft = None
if "sku_draft_acc_idx" not in st.session_state:
    st.session_state.sku_draft_acc_idx = None
if "sku_widget_rev" not in st.session_state:
    st.session_state.sku_widget_rev = 0
if "sku_strict_image" not in st.session_state:
    st.session_state.sku_strict_image = True


# ─── 页面标题 ───────────────────────────────────────────────────────────────

st.title("🛍️ 拼多多商品批量上架管理系统")

tab_ctrl, tab_delist, tab_logs, tab_stats, tab_ai = st.tabs(
    ["⚙️ 控制台", "📦 批量下架", "📋 实时日志", "📊 统计看板", "🤖 AI 指令"]
)


# ═══════════════════════════════════════════════════════════════════════
# Tab 1: 控制台
# ═══════════════════════════════════════════════════════════════════════
with tab_ctrl:
    cfg = st.session_state.cfg
    # SKU 手动编辑器已停用，统一走多规格测试目录
    if st.session_state.sku_editor_idx is not None:
        st.session_state.sku_editor_idx = None
        st.session_state.sku_draft = None
        st.session_state.sku_draft_acc_idx = None

    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("店铺账号")
        for i, acc in enumerate(cfg["accounts"]):
            with st.expander(f"🏪 {acc['account_id']}", expanded=False):
                cfg["accounts"][i]["enabled"] = st.toggle(
                    "启用", value=acc["enabled"], key=f"acc_{i}"
                )
                cfg["accounts"][i]["username"] = st.text_input(
                    "登录手机号/账号", value=acc.get("username", ""), key=f"user_{i}"
                )
                cfg["accounts"][i]["password"] = st.text_input(
                    "登录密码", value=acc.get("password", ""), type="password", key=f"pwd_{i}"
                )
                render_account_multi_spec_config(cfg, i, acc)

    with c_right:
        st.subheader("商品信息")
        pi = cfg["global_product_info"]
        pi["category_keyword"] = st.text_input(
            "类目关键词", value=pi.get("category_keyword", ""), key="pi_cat"
        )

        title_mode = pi.get("title_mode", "custom")
        mode_options = ["自定义", "AI 生成", "页面AI生成"]
        mode_index = {"custom": 0, "ai": 1, "page_ai": 2}.get(title_mode, 0)
        mode_label = st.radio(
            "商品标题来源",
            mode_options,
            index=mode_index,
            horizontal=True,
            key="pi_title_mode_radio",
        )
        mode_map = {"自定义": "custom", "AI 生成": "ai", "页面AI生成": "page_ai"}
        pi["title_mode"] = mode_map.get(mode_label, "custom")

        if pi["title_mode"] == "custom":
            pi["title"] = st.text_input(
                "商品标题",
                value=pi.get("title", ""),
                key="pi_title",
                placeholder="手动输入标题",
            )
        elif pi["title_mode"] == "page_ai":
            st.info(
                "已选择 **页面AI生成**：上架时上传主图后，将等待拼多多页面出现 "
                "「AI智能推荐标题 … **立即使用**」，并自动点击填充标题（约 5–35 秒）。"
                "此处无需填写。"
            )
        else:
            st.info(
                "已选择 **AI 生成**：点击「开始上架」时，将用 **GLM-5V-Turbo** 分析该店 **1.jpg + 6.jpg** 并生成标题；"
                "此处无需填写。"
            )

        pi["product_code"] = st.text_input(
            "商品编码", value=pi.get("product_code", ""), key="pi_pcode"
        )

    st.divider()
    b1, b2, b3 = st.columns([1, 1, 2])

    with b1:
        if st.button("💾 保存配置", use_container_width=True):
            save_config(cfg)
            st.success("配置已保存！")

    with b2:
        if not is_proc_running("main_proc"):
            if st.button("🚀 开始上架", type="primary", use_container_width=True):
                save_config(cfg)
                st.session_state["main_proc"] = run_subprocess("multi_spec_main.py", MAIN_LOG)
                st.rerun()
        else:
            if st.button("⏹ 停止任务", type="secondary", use_container_width=True):
                st.session_state["main_proc"].terminate()
                st.session_state["main_proc"] = None
                st.rerun()

    with b3:
        if is_proc_running("main_proc"):
            st.info("⏳ 多规格上架任务运行中，切换到「实时日志」查看进度")
        else:
            p = st.session_state.get("main_proc")
            if p is not None:
                code = p.poll()
                if code == 0:
                    st.success("✅ 上次任务正常完成")
                elif code is not None:
                    st.error(f"❌ 上次任务异常退出（返回码: {code}）")


# ═══════════════════════════════════════════════════════════════════════
# Tab 2: 批量下架
# ═══════════════════════════════════════════════════════════════════════
with tab_delist:
    render_delist_tab(
        st.session_state.cfg,
        save_config,
        run_subprocess,
        is_proc_running,
        read_log,
        render_log_html,
        DELIST_LOG,
    )


# ═══════════════════════════════════════════════════════════════════════
# Tab 3: 实时日志
# ═══════════════════════════════════════════════════════════════════════
with tab_logs:
    h1, h2 = st.columns([4, 1])
    with h2:
        auto_ref = st.checkbox("自动刷新", value=is_proc_running("main_proc"), key="auto_ref_logs")

    log_text = read_log(MAIN_LOG)
    if log_text.strip():
        line_count = log_text.count("\n")
        st.caption(f"📄 `{MAIN_LOG.name}` · {line_count} 行")
        st.markdown(render_log_html(log_text), unsafe_allow_html=True)

        with st.expander("📥 原始文本"):
            st.code(log_text, language=None)
    else:
        st.info("暂无日志，请在「控制台」启动上架任务。")

    if auto_ref:
        time.sleep(2)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# Tab 3: 统计看板
# ═══════════════════════════════════════════════════════════════════════
with tab_stats:
    log_text_s = read_log(MAIN_LOG)

    if not log_text_s.strip():
        st.info("暂无数据，请先运行上架任务。")
    else:
        acc_status = parse_stats(log_text_s)

        total = len(acc_status)
        counts = {s: sum(1 for v in acc_status.values() if v["status"] == s)
                  for s in ["success", "failed", "warning", "running", "skipped", "pending"]}

        m_cols = st.columns(6)
        m_cols[0].metric("账号总数", total)
        m_cols[1].metric("✅ 成功", counts["success"])
        m_cols[2].metric("❌ 失败", counts["failed"])
        m_cols[3].metric("⚠️ 警告", counts["warning"])
        m_cols[4].metric("🔄 进行中", counts["running"])
        m_cols[5].metric("⏳ 待执行", counts["pending"])

        st.divider()
        st.subheader("各账号状态")

        items = sorted(acc_status.items())
        for row_start in range(0, len(items), 3):
            row_items = items[row_start: row_start + 3]
            card_cols = st.columns(3)
            for j, (acc_id, info) in enumerate(row_items):
                status = info["status"]
                icon = STATUS_ICON.get(status, "❓")
                bg = STATUS_COLOR.get(status, "#fafafa")
                last_msg = info["last_msg"]
                short_msg = (last_msg[:50] + "…") if len(last_msg) > 50 else last_msg
                with card_cols[j]:
                    st.markdown(
                        f'<div style="background:{bg};border-radius:8px;padding:14px 16px;'
                        f'border:1px solid #e0e0e0;margin-bottom:8px">'
                        f'<div style="font-size:18px;font-weight:700">{icon} {acc_id}</div>'
                        f'<div style="color:#555;margin:4px 0">状态: <b>{status}</b></div>'
                        f'<div style="font-size:12px;color:#888">{info["lines"]} 条日志</div>'
                        f'<div style="font-size:11px;color:#aaa;margin-top:4px;font-family:monospace">'
                        f'{short_msg}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        # 状态分布图
        if acc_status:
            st.divider()
            st.subheader("状态分布")
            import pandas as pd
            dist = {}
            for info in acc_status.values():
                s = info["status"]
                dist[s] = dist.get(s, 0) + 1
            df_dist = pd.DataFrame(list(dist.items()), columns=["状态", "数量"])
            st.bar_chart(df_dist.set_index("状态"))


# ═══════════════════════════════════════════════════════════════════════
# Tab 4: AI 指令
# ═══════════════════════════════════════════════════════════════════════
with tab_ai:
    st.subheader("自然语言驱动上架")
    st.caption("由通义千问解析指令，自动提取商品参数并调用上架流程。")

    instruction = st.text_area(
        "输入上架指令",
        placeholder="例如：帮我上架一款玩偶，类目选「玩偶」，标题叫「精选萌系玩偶摆件」，拼单价18块，单买价25块。",
        height=100,
        key="ai_instruction",
    )

    ai_b1, ai_b2 = st.columns([1, 3])
    with ai_b1:
        if not is_proc_running("ai_proc"):
            if st.button("🤖 执行指令", type="primary", use_container_width=True, disabled=not instruction.strip()):
                st.session_state["ai_proc"] = run_subprocess(
                    "agent_gateway.py", AI_LOG, extra_args=[instruction.strip()]
                )
                st.rerun()
        else:
            if st.button("⏹ 停止", type="secondary", use_container_width=True):
                st.session_state["ai_proc"].terminate()
                st.session_state["ai_proc"] = None
                st.rerun()

    with ai_b2:
        if is_proc_running("ai_proc"):
            st.info("⏳ AI 正在解析并执行上架任务…")
        else:
            p = st.session_state.get("ai_proc")
            if p is not None:
                code = p.poll()
                if code == 0:
                    st.success("✅ AI 任务已完成")
                elif code is not None:
                    st.error(f"❌ AI 任务异常退出（返回码: {code}）")

    ai_log = read_log(AI_LOG)
    if ai_log.strip():
        st.markdown("**执行日志**")
        st.markdown(render_log_html(ai_log), unsafe_allow_html=True)
    else:
        st.info("暂无 AI 执行记录。")

    if is_proc_running("ai_proc"):
        time.sleep(2)
        st.rerun()
