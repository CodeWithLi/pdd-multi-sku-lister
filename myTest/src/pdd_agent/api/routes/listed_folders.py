"""已上架素材文件夹 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.listed_folders import ListedAssetFolderListResponse, ListedAssetFolderOut
from pdd_agent.api.services.config_service import get_account_or_none
from pdd_agent.db.repositories import list_listed_asset_folders
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/listed-folders", tags=["listed-folders"])


def _row_out(row) -> ListedAssetFolderOut:
    return ListedAssetFolderOut(
        record_id=row.record_id,
        account_id=row.account_id,
        folder_selector=row.folder_selector,
        family_code=row.family_code or "",
        image_set=row.image_set or "",
        product_code=row.product_code or "",
        listing_label=row.listing_label or "",
        asset_path=row.asset_path or "",
        source_run_id=row.source_run_id or "",
        source_kind=row.source_kind or "listing",
        pipeline_id=row.pipeline_id or "",
        pdd_product_id=row.pdd_product_id or "",
        listed_at=row.listed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=ListedAssetFolderListResponse)
def list_listed_folders(
    account_id: str = "",
    family_code: str = "",
    image_set: str = "",
    product_code: str = "",
    source_kind: str = "",
    limit: int = 200,
):
    if not is_database_available():
        return ListedAssetFolderListResponse(items=[], total=0)
    account_id = str(account_id or "").strip()
    if account_id and not get_account_or_none(account_id):
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    rows = list_listed_asset_folders(
        account_id=account_id,
        family_code=family_code.strip(),
        image_set=image_set.strip(),
        product_code=product_code.strip(),
        source_kind=source_kind.strip(),
        limit=limit,
    )
    items = [_row_out(row) for row in rows]
    return ListedAssetFolderListResponse(items=items, total=len(items))
