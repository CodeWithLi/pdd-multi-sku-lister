"""批量上架任务入口（由 Streamlit 子进程调用）。"""
import sys

from pdd_auto.config import load_config
from pdd_auto.listing.runner import run_listing_job

sys.stdout.reconfigure(encoding="utf-8")

if __name__ == "__main__":
    run_listing_job(load_config())
