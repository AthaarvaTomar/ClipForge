from fastapi import APIRouter

from app.api.v1.endpoints import (
    assets,
    clips,
    highlights,
    indexing,
    jobs,
    metrics,
    presets,
    timelines,
    transcripts,
    tus,
    videos,
)

api_router = APIRouter()
api_router.include_router(videos.router)
api_router.include_router(tus.router)
api_router.include_router(indexing.router)
api_router.include_router(jobs.router)
api_router.include_router(transcripts.router)
api_router.include_router(highlights.router)
api_router.include_router(clips.router)
api_router.include_router(presets.router)
api_router.include_router(timelines.router)
api_router.include_router(assets.router)
api_router.include_router(metrics.router)
