"""上架前校验 Skill：汇总 error/warning，供 LangGraph preflight 节点使用。"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from pdd_agent.core.config import YamlSettings
from pdd_agent.domain.models import PreflightIssue, PreflightReport
from pdd_agent.skills.base import Skill
from pdd_agent.skills.listing.catalog import parse_listing_target


def run_preflight(
    product_codes: list[str],
    settings: YamlSettings,
    *,
    include_excel_missing_previews: bool = False,
    slot_alignment_test: bool = False,
    assets_root: Path | None = None,
) -> PreflightReport:
    """
    批量校验商品编码。
    error：目录不存在、无有效 SKU；warning：缺图、Excel 缺行等。
    """
    report = PreflightReport()
    for code in product_codes:
        units = parse_listing_target(
            code,
            settings,
            include_excel_missing_previews=include_excel_missing_previews,
            slot_alignment_test=slot_alignment_test,
            assets_root=assets_root,
        )
        if not units:
            report.issues.append(
                PreflightIssue(level="error", message=f"商品目录不存在或无套图: {code}", listing_label=code)
            )
            continue
        for unit in units:
            report.units.append(unit)
            if not unit.skus:
                report.issues.append(
                    PreflightIssue(
                        level="error",
                        message="无有效 SKU（检查 Excel 与预览图）",
                        listing_label=unit.listing_label,
                    )
                )
            if not unit.carousel_images:
                report.issues.append(
                    PreflightIssue(
                        level="warning",
                        message="主图为空",
                        listing_label=unit.listing_label,
                    )
                )
            if not unit.detail_images:
                report.issues.append(
                    PreflightIssue(
                        level="warning",
                        message="详情图为空",
                        listing_label=unit.listing_label,
                    )
                )
            for w in unit.warnings:
                if "槽位对齐" in w:
                    report.issues.append(
                        PreflightIssue(level="error", message=w, listing_label=unit.listing_label)
                    )
                else:
                    report.issues.append(
                        PreflightIssue(level="warning", message=w, listing_label=unit.listing_label)
                    )
    return report


class PreflightSkill(Skill):
    """LangChain Tool：逗号分隔商品编码，返回校验摘要。"""

    name = "preflight_listing"
    description = "上架前校验素材目录与 Excel"

    def as_tool(self) -> StructuredTool:
        def _run(product_codes: str) -> str:
            from pdd_agent.core.config import load_yaml_settings

            codes = [c.strip() for c in product_codes.split(",") if c.strip()]
            report = run_preflight(codes, load_yaml_settings())
            errors = sum(1 for i in report.issues if i.level == "error")
            warnings = sum(1 for i in report.issues if i.level == "warning")
            return f"units={len(report.units)} errors={errors} warnings={warnings} ok={report.ok}"

        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=_run,
        )
