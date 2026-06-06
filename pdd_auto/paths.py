"""项目路径常量（相对仓库根目录）。"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
LOG_DIR = PROJECT_ROOT / "logs"
ERROR_SCREENSHOT_DIR = LOG_DIR / "errors"
CHROME_PROFILES_DIR = PROJECT_ROOT / "ChromeProfiles"
ARCHIVE_DIR = PROJECT_ROOT / "archive"
PRODUCTS_DIR = ARCHIVE_DIR / "products"
PICTURE_DIR = ARCHIVE_DIR / "picture"
LEGACY_PRODUCTS_REL = "archive/products"
MULTI_SPEC_DIR = PROJECT_ROOT / "多规格测试"


def chrome_profile_path(account_id: str) -> str:
    return str(CHROME_PROFILES_DIR / f"pdd_{account_id}")


def error_screenshot_path(filename: str) -> str:
    """报错截图统一保存到 logs/errors/ 目录。"""
    ERROR_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return str(ERROR_SCREENSHOT_DIR / filename)
