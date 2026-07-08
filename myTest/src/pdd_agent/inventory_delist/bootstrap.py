"""库存下架模块 — 应用集成入口（尽量少改 app.py）。"""

from __future__ import annotations

from fastapi import FastAPI

from pdd_agent.inventory_delist.routes import router as inventory_delist_router
from pdd_agent.inventory_delist.scheduler import get_inventory_delist_scheduler


def register_inventory_delist(app: FastAPI) -> None:
    app.include_router(inventory_delist_router, prefix="/api")


def start_inventory_delist_scheduler() -> None:
    get_inventory_delist_scheduler().start()


async def stop_inventory_delist_scheduler() -> None:
    await get_inventory_delist_scheduler().stop()
