"""项目路径常量（均以 dyTest 根目录为基准）。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SKILLS_MD_DIR = PROJECT_ROOT / "skills"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
DEFAULT_AGENTS_PATH = CONFIG_DIR / "agents.yaml"
