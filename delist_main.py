"""批量下架任务入口（由 Streamlit 子进程调用）。"""
import sys

from pdd_auto.delist.runner import main

sys.stdout.reconfigure(encoding="utf-8")

if __name__ == "__main__":
    main()
