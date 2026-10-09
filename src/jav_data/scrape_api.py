"""Browser controls and pasted URL queue API."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jav_data.models import ProductFolder, ScrapeJob
from jav_data.scraper import product_url

router = APIRouter(prefix="/api", tags=["Scraping"])


class URLBatch(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)
    product_folder_id: int | None = Field(default=None, ge=1)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values):
        return list(dict.fromkeys(product_url(url) for url in values))


def job_dict(job):
    return {
        field: getattr(job, field)
        for field in ("id", "url", "status", "attempts", "error", "movie_id")
    }


@router.get("/session")
def session_status(request: Request):
    return {"status": request.app.state.worker.state}


@router.post("/session/{action}")
async def browser_action(action: str, request: Request):
    if action not in {"open", "open:dmm", "open:mgs", "ready", "close"}:
        raise HTTPException(404, "Unknown session action")
    if action == "close":
        request.app.state.discovery.cancel()
    future = request.app.state.worker.command(action)
    try:
        return await asyncio.wrap_future(future)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/scrape-jobs", status_code=201)
def enqueue(payload: URLBatch, request: Request):
    with request.app.state.library_lock.work(), Session(request.app.state.engine) as session:
        folder_id = payload.product_folder_id or session.scalar(
            select(ProductFolder.id).order_by(ProductFolder.id)
        )
        if folder_id is None:
            raise HTTPException(400, "Add a library folder in Database & Library first")
        if session.get(ProductFolder, folder_id) is None:
            raise HTTPException(404, "Library not found")
        jobs = []
        for url in payload.urls:
            job = session.scalar(
                select(ScrapeJob).where(
                    ScrapeJob.url == url,
                    ScrapeJob.status.in_(["queued", "running", "awaiting_session"]),
                )
            )
            if job is None:
                job = ScrapeJob(url=url, product_folder_id=folder_id)
                session.add(job)
            jobs.append(job)
        session.commit()
        return [job_dict(job) for job in jobs]


@router.get("/scrape-jobs")
def list_jobs(request: Request, limit: int = Query(100, ge=1, le=200)):
    with Session(request.app.state.engine) as session:
        return [
            job_dict(job)
            for job in session.scalars(select(ScrapeJob).order_by(ScrapeJob.id.desc()).limit(limit))
        ]


@router.post("/scrape-history/clear")
def clear_history(request: Request):
    with Session(request.app.state.engine) as session:
        result = session.execute(
            delete(ScrapeJob).where(ScrapeJob.status.in_(["completed", "failed"]))
        )
        session.commit()
        return {"cleared": result.rowcount}


@router.post("/scrape-jobs/{job_id}/retry")
def retry(job_id: int, request: Request):
    with request.app.state.library_lock.work(), Session(request.app.state.engine) as session:
        job = session.get(ScrapeJob, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if job.status in {"running", "queued"}:
            raise HTTPException(409, "Job is already active")
        if (
            job.product_folder_id is None
            or session.get(ProductFolder, job.product_folder_id) is None
        ):
            raise HTTPException(400, "Library removed; add the URL again to a library")
        job.status, job.error = "queued", None
        session.commit()
        return job_dict(job)
