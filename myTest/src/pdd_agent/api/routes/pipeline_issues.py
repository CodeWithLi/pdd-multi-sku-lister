"""整合链路专用报错 API（独立于 failures / runs）。"""

from fastapi import APIRouter, HTTPException, Query

from pdd_agent.api.schemas.pipeline_issues import (
    PipelineIssueListResponse,
    PipelineIssueOut,
    PipelineIssueSummaryResponse,
)
from pdd_agent.api.services.pipeline_issue_report_service import (
    get_pipeline_issue,
    list_pipeline_issues,
    pipeline_issue_summary,
)
from pdd_agent.db.session import is_database_available

router = APIRouter(prefix="/pipeline-issues", tags=["pipeline-issues"])


def _out(row: dict) -> PipelineIssueOut:
    return PipelineIssueOut(**row)


@router.get("", response_model=PipelineIssueListResponse)
def list_issues(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=200),
    pipeline_id: str = Query(default=""),
    batch_id: str = Query(default=""),
    account_id: str = Query(default=""),
    stage: str = Query(default=""),
    severity: str = Query(default=""),
    keyword: str = Query(default=""),
):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL unavailable")
    data = list_pipeline_issues(
        page=page,
        page_size=page_size,
        pipeline_id=pipeline_id.strip(),
        batch_id=batch_id.strip(),
        account_id=account_id.strip(),
        stage=stage.strip(),
        severity=severity.strip(),
        keyword=keyword.strip(),
    )
    return PipelineIssueListResponse(
        items=[_out(item) for item in data["items"]],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
    )


@router.get("/summary/{pipeline_id}", response_model=PipelineIssueSummaryResponse)
def issue_summary(pipeline_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL unavailable")
    stats = pipeline_issue_summary(pipeline_id)
    return PipelineIssueSummaryResponse(pipeline_id=pipeline_id, **stats)


@router.get("/{issue_id}", response_model=PipelineIssueOut)
def get_issue(issue_id: str):
    if not is_database_available():
        raise HTTPException(status_code=503, detail="MySQL unavailable")
    row = get_pipeline_issue(issue_id)
    if not row:
        raise HTTPException(status_code=404, detail="issue not found")
    return _out(row)
