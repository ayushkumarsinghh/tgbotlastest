from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["results"])


@router.get("/api/results/plus")
async def results_plus(request: Request):
    content, count = await request.app.state.results.read_result("plus")
    return {"content": content, "count": count}


@router.get("/api/results/done")
async def results_done(request: Request):
    content, count = await request.app.state.results.read_result("done")
    return {"content": content, "count": count}


@router.get("/api/results/free")
async def results_free(request: Request):
    # Legacy endpoint — UI không còn dùng
    content, count = await request.app.state.results.read_result("free")
    return {"content": content, "count": count}
