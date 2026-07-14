from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDD = ROOT.parent / "myTest" / "src" / "pdd_agent"
DY = ROOT / "src" / "dy_agent"

FILES = [
    "skills/listing/spec_labels.py",
    "skills/listing/listing_spec_pipeline.py",
    "llm/vision.py",
]

REPLACEMENTS = [
    ("pdd_agent", "dy_agent"),
    (
        "from pdd_agent.db.repositories import get_cached_style_color, upsert_cached_style_color",
        "from dy_agent.skills.listing.style_color_cache import get_cached_style_color, upsert_cached_style_color",
    ),
]

PIPELINE_DROP = """    removed = filter_listing_unit_skus_by_platform_skip(unit)
    if removed:
        from dy_agent.core.logging import get_logger

        get_logger(__name__).info(
            "[%s] platform-skipped sibling styles excluded from specs: %s",
            unit.listing_label,
            ", ".join(removed),
        )
"""


def main() -> None:
    for rel in FILES:
        src = PDD / Path(rel)
        dst = DY / Path(rel)
        text = src.read_text(encoding="utf-8")
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if "listing_spec_pipeline" in rel:
            text = text.replace(
                "from dy_agent.skills.listing.platform_skip_siblings import filter_listing_unit_skus_by_platform_skip\n",
                "",
            )
            text = text.replace(PIPELINE_DROP.replace("pdd_agent", "dy_agent"), "")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        print(f"OK {rel}")


if __name__ == "__main__":
    main()
