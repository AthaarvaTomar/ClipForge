from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import DummyJobRequest, JobResponse
from app.services.job_service import JobService
from app.tasks.dummy_task import run_dummy_task

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post(
    "/dummy",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Launch a dummy task simulating progress 0 to 100",
)
def create_dummy_job(
    request: DummyJobRequest = DummyJobRequest(),
    db: Session = Depends(get_db),
) -> Job:
    """Create a dummy background task and dispatch to Celery."""
    job = JobService.create_job(db=db, job_type="dummy")
    run_dummy_task.delay(
        job_id=job.id,
        steps=request.steps,
        delay_seconds=request.delay_seconds,
    )
    return job


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get job status and progress",
)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
) -> Job:
    """Fetch status and progress percentage for a background job."""
    job = JobService.get_job(db=db, job_id=job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found",
        )
    return job


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    summary="Cancel a running or pending background job",
)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> Job:
    """Cancel a background job by ID."""
    job = JobService.get_job(db=db, job_id=job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id '{job_id}' not found",
        )

    updated = JobService.cancel_job(job_id)
    assert updated is not None
    return updated
