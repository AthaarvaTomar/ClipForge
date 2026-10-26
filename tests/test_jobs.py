from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app
from app.tasks.dummy_task import run_dummy_task


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    """Ensure Celery tasks execute synchronously within tests."""
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_job_service_progress_lifecycle(db_session: Session) -> None:
    # 1. Create Job
    job = JobService.create_job(db=db_session, job_type="test_lifecycle")
    assert job.id is not None
    assert job.status == "PENDING"
    assert job.progress == 0

    # 2. Update to 50%
    updated = JobService.update_progress(job_id=job.id, progress=50, status="PROCESSING")
    assert updated is not None
    assert updated.status == "PROCESSING"
    assert updated.progress == 50

    # 3. Update to 100% COMPLETED
    completed = JobService.update_progress(
        job_id=job.id,
        progress=100,
        status="COMPLETED",
        result_data={"detail": "all done"},
    )
    assert completed is not None
    assert completed.status == "COMPLETED"
    assert completed.progress == 100
    assert completed.result_data == {"detail": "all done"}


def test_dummy_task_direct_execution(db_session: Session) -> None:
    job = JobService.create_job(db=db_session, job_type="dummy_direct")
    result = run_dummy_task(job_id=job.id, steps=4, delay_seconds=0.0)

    assert result["progress"] == 100
    assert result["status"] == "COMPLETED"

    # Query DB to verify final state
    db_session.expire_all()
    refreshed = JobService.get_job(db=db_session, job_id=job.id)
    assert refreshed is not None
    assert refreshed.progress == 100
    assert refreshed.status == "COMPLETED"
    assert refreshed.result_data is not None
    assert refreshed.result_data["steps_completed"] == 4


def test_dummy_task_api_e2e(client: TestClient) -> None:
    # 1. Trigger dummy job via POST endpoint
    response = client.post(
        "/api/jobs/dummy",
        json={"steps": 5, "delay_seconds": 0.0},
    )
    assert response.status_code == 202
    data = response.json()
    job_id = data["id"]
    assert job_id is not None
    assert data["job_type"] == "dummy"

    # 2. Query status via GET /api/jobs/{id}
    status_response = client.get(f"/api/jobs/{job_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["id"] == job_id
    assert status_data["status"] == "COMPLETED"
    assert status_data["progress"] == 100
    assert status_data["result_data"]["steps_completed"] == 5


def test_get_non_existent_job(client: TestClient) -> None:
    response = client.get("/api/jobs/non-existent-uuid")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
