#!/usr/bin/env python
"""启动飞书联调 API（默认 8001，与主 API 8010/8000 隔离）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

# 允许在未 pip install -e 时从仓库根运行
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pdd_agent.integrations.feishu.test_app import create_feishu_test_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Feishu test API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(create_feishu_test_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
