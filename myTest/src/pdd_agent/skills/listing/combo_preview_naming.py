"""规格图（组合预览图）文件名与文件夹名前缀校验。

素材目录规则（与 catalog 一致）：
- 1-9 为主图 / 详情 / 商品素材，不参与本校验
- 其余图片文件视为规格图（单款或组合款）
- 规格图文件名必须以所在文件夹名开头，例如文件夹 ``AXBD001A`` 只接受
  ``AXBD001A.jpg``、``AXBD001A+YKL001J.jpg`` 等
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pdd_agent.domain.models import ListingUnit

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ComboPreviewNamingIssue:
    """单张规格图命名不符合文件夹前缀规则。"""

    folder_name: str
    filename: str
    listing_label: str = ""

    @property
    def message(self) -> str:
        label = self.listing_label or self.folder_name
        return (
            f"[{label}] 组合图文件名必须以文件夹名 {self.folder_name} 开头: {self.filename}"
        )


def is_numbered_asset_image(path: Path) -> bool:
    """是否为 1-9 编号主图/详情/商品素材（不参与规格图命名校验）。"""
    if path.suffix.lower() not in IMAGE_EXTS:
        return False
    stem = path.stem.strip()
    if not stem.isdigit():
        return False
    return 1 <= int(stem) <= 9


def collect_combo_preview_images(code_dir: Path) -> list[Path]:
    """收集目录下除 1-9 编号图以外的规格图文件。"""
    if not code_dir.is_dir():
        return []
    files = [
        p
        for p in code_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not is_numbered_asset_image(p)
    ]
    return sorted(files, key=lambda p: p.name.casefold())


def preview_stem_matches_folder(stem: str, folder_name: str) -> bool:
    """规格图文件名是否属于该编码文件夹（与 catalog._preview_stem_matches_code_dir 一致）。"""
    text = str(stem or "").strip()
    dir_key = str(folder_name or "").strip().casefold()
    if not text or not dir_key:
        return False
    if "+" in text:
        style_part = text.split("+", 1)[0].strip().casefold()
        if style_part == dir_key:
            return True
        return dir_key.startswith(style_part) and len(style_part) < len(dir_key)
    return text.casefold() == dir_key


def validate_combo_preview_naming(
    code_dir: Path,
    *,
    listing_label: str = "",
) -> list[ComboPreviewNamingIssue]:
    """校验单个商品编码目录下所有规格图是否以文件夹名开头。"""
    folder_name = code_dir.name.strip()
    if not folder_name:
        return []

    issues: list[ComboPreviewNamingIssue] = []
    for preview in collect_combo_preview_images(code_dir):
        stem = preview.stem.strip()
        if stem and preview_stem_matches_folder(stem, folder_name):
            continue
        issues.append(
            ComboPreviewNamingIssue(
                folder_name=folder_name,
                filename=preview.name,
                listing_label=listing_label,
            )
        )
    return issues


def validate_listing_unit_combo_preview_naming(unit: ListingUnit) -> list[ComboPreviewNamingIssue]:
    """校验 ListingUnit 对应素材目录的规格图命名。"""
    return validate_combo_preview_naming(
        unit.root,
        listing_label=unit.listing_label,
    )


def format_combo_preview_naming_issue(issue: ComboPreviewNamingIssue) -> str:
    return issue.message


def summarize_combo_preview_naming(code_dir: Path) -> dict[str, int | list[str]]:
    """便于调试：返回规格图数量与命名不合规文件列表。"""
    folder_name = code_dir.name.strip()
    previews = collect_combo_preview_images(code_dir)
    mismatches = [
        issue.filename
        for issue in validate_combo_preview_naming(code_dir, listing_label=folder_name)
    ]
    return {
        "folder_name": folder_name,
        "combo_preview_count": len(previews),
        "mismatch_count": len(mismatches),
        "mismatch_files": mismatches,
    }
