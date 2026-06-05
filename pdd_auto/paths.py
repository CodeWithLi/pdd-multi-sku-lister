"""项目路径常量（相对仓库根目录）。"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
LOG_DIR = PROJECT_ROOT / "logs"
CHROME_PROFILES_DIR = PROJECT_ROOT / "ChromeProfiles"
PRODUCTS_DIR = PROJECT_ROOT / "products"
MULTI_SPEC_DIR = PROJECT_ROOT / "多规格测试"


def chrome_profile_path(account_id: str) -> str:
    return str(CHROME_PROFILES_DIR / f"pdd_{account_id}")


def error_screenshot_path(filename: str) -> str:
    return str(PROJECT_ROOT / filename)
