"""Product style color cache APIs."""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.style_colors import (
    StyleColorCreateIn,
    StyleColorListResponse,
    StyleColorOut,
    StyleColorUpdateIn,
)
from pdd_agent.db.repositories import (
    create_style_color,
    delete_style_color,
    get_style_color_row,
    search_style_colors,
    update_style_color,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/style-colors", tags=["style-colors"])


def _row_out(row) -> StyleColorOut:
    return StyleColorOut(
        product_code=row.product_code,
        color_label=row.color_label,
        source=row.source or "ai",
        image_path=row.image_path or "",
        image_mtime=float(row.image_mtime or 0.0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_db():
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL style color cache unavailable")


@router.get("", response_model=StyleColorListResponse)
def style_colors_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    product_code: str = "",
    color_label: str = "",
    source: str = "",
):
    _require_db()
    rows, total = search_style_colors(
        page=page,
        page_size=page_size,
        product_code=product_code.strip(),
        color_label=color_label.strip(),
        source=source.strip(),
    )
    return StyleColorListResponse(
        items=[_row_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{product_code}", response_model=StyleColorOut)
def style_color_detail(product_code: str):
    _require_db()
    row = get_style_color_row(product_code)
    if not row:
        raise HTTPException(status_code=404, detail=f"style color not found: {product_code}")
    return _row_out(row)


@router.post("", response_model=StyleColorOut, status_code=201)
def style_color_create(body: StyleColorCreateIn):
    _require_db()
    code = body.product_code.strip()
    label = body.color_label.strip()
    if not code or not label:
        raise HTTPException(status_code=422, detail="product_code and color_label are required")
    try:
        row = create_style_color(
            code,
            label,
            source="manual",
            image_path=body.image_path.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _row_out(row)


@router.put("/{product_code}", response_model=StyleColorOut)
def style_color_update(product_code: str, body: StyleColorUpdateIn):
    _require_db()
    label = body.color_label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="color_label is required")
    row = update_style_color(
        product_code,
        label,
        image_path=body.image_path,
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"style color not found: {product_code}")
    return _row_out(row)


@router.delete("/{product_code}")
def style_color_delete(product_code: str):
    _require_db()
    if not delete_style_color(product_code):
        raise HTTPException(status_code=404, detail=f"style color not found: {product_code}")
    return {"ok": True, "product_code": product_code.strip().upper()}
