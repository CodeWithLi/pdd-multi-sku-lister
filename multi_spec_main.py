"""多规格测试模式上架入口。

用法:
  python multi_spec_main.py                    # 跑 config 里 enabled 的店
  python multi_spec_main.py BD199A             # 指定商品编码
  python multi_spec_main.py --dry-run BD199A   # 只解析目录，不打开浏览器
"""
import sys

from pdd_auto.config import load_config
from pdd_auto.listing.multi_spec_runner import run_multi_spec_job
from pdd_auto.log_utils import install_safe_stdout

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
install_safe_stdout()


def main():
    args = sys.argv[1:]
    dry_run = False
    product_code = None

    if "--dry-run" in args:
        dry_run = True
        args = [a for a in args if a != "--dry-run"]
    if args:
        product_code = args[0].strip()

    config = load_config()
    run_multi_spec_job(config, dry_run=dry_run, product_code=product_code)


if __name__ == "__main__":
    main()
