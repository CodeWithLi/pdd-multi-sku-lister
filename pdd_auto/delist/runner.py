"""批量下架任务入口。"""
from pdd_auto.config import load_config
from pdd_auto.delist.automation import run_delist_job


def main():
    run_delist_job(load_config())


if __name__ == "__main__":
    main()
