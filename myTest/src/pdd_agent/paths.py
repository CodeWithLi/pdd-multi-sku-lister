"""项目路径常量（均以 myTest 根目录为基准）。"""

from pathlib import Path

# myTest/ 根目录（src/pdd_agent 上两级）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# src/ 目录
SRC_ROOT = Path(__file__).resolve().parents[1]
# config/、skills/ 等静态资源
CONFIG_DIR = PROJECT_ROOT / "config"
SKILLS_MD_DIR = PROJECT_ROOT / "skills"
# Agent 系统提示词目录
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
DEFAULT_AGENTS_PATH = CONFIG_DIR / "agents.yaml"
