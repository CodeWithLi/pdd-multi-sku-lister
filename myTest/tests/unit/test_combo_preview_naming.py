"""combo_preview_naming 规格图文件名前缀校验。"""

from pathlib import Path

from pdd_agent.skills.listing.combo_preview_naming import (
    collect_combo_preview_images,
    preview_stem_matches_folder,
    summarize_combo_preview_naming,
    validate_combo_preview_naming,
)


def test_collect_combo_preview_images_excludes_numbered_1_to_9(tmp_path: Path):
    code_dir = tmp_path / "AXBD001A"
    code_dir.mkdir()
    for index in range(1, 10):
        (code_dir / f"{index}.jpg").write_bytes(b"img")
    (code_dir / "AXBD001A.jpg").write_bytes(b"solo")
    (code_dir / "AXBD001A+YKL001A.jpg").write_bytes(b"combo")
    (code_dir / "AXB001A+YKL001J.jpg").write_bytes(b"bad")

    names = [p.name for p in collect_combo_preview_images(code_dir)]
    assert names == [
        "AXB001A+YKL001J.jpg",
        "AXBD001A+YKL001A.jpg",
        "AXBD001A.jpg",
    ]


def test_preview_stem_matches_folder():
    folder = "AXBD001A"
    assert preview_stem_matches_folder("AXBD001A", folder)
    assert preview_stem_matches_folder("AXBD001A+YKL001J", folder)
    assert not preview_stem_matches_folder("AXB001A+YKL001J", folder)
    assert not preview_stem_matches_folder("AXB001A", folder)


def test_validate_combo_preview_naming_reports_mismatch(tmp_path: Path):
    code_dir = tmp_path / "AXBD001A"
    code_dir.mkdir()
    (code_dir / "AXBD001A.jpg").write_bytes(b"solo")
    (code_dir / "AXB001A+YKL001J.jpg").write_bytes(b"bad1")
    (code_dir / "AXB001A+YKL004A.jpg").write_bytes(b"bad2")

    issues = validate_combo_preview_naming(code_dir, listing_label="AXBD001A/第二套图")
    assert len(issues) == 2
    assert issues[0].filename == "AXB001A+YKL001J.jpg"
    assert issues[0].folder_name == "AXBD001A"
    assert "必须以文件夹名 AXBD001A 开头" in issues[0].message
    assert "[AXBD001A/第二套图]" in issues[0].message


def test_validate_combo_preview_naming_all_valid(tmp_path: Path):
    code_dir = tmp_path / "AXBD001A"
    code_dir.mkdir()
    (code_dir / "AXBD001A.jpg").write_bytes(b"solo")
    (code_dir / "AXBD001A+YKL001A.jpg").write_bytes(b"combo")

    issues = validate_combo_preview_naming(code_dir)
    assert issues == []


def test_summarize_combo_preview_naming(tmp_path: Path):
    code_dir = tmp_path / "AXBD001A"
    code_dir.mkdir()
    (code_dir / "AXBD001A.jpg").write_bytes(b"solo")
    (code_dir / "AXB001A+YKL001J.jpg").write_bytes(b"bad")

    summary = summarize_combo_preview_naming(code_dir)
    assert summary["combo_preview_count"] == 2
    assert summary["mismatch_count"] == 1
    assert summary["mismatch_files"] == ["AXB001A+YKL001J.jpg"]
