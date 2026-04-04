from __future__ import annotations

import asyncio
import json
import platform
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dialogs import select_folder, select_zip_files
from .models import MediaSummary, ProcessStats
from .pipeline import analyze_sources, process_sources


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _package_version() -> str:
    try:
        return metadata.version("snapchat-export-organizer")
    except metadata.PackageNotFoundError:
        return "0.1.0"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "web_static"


def _index_path() -> Path:
    return _static_dir() / "index.html"


FALLBACK_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Snapchat Export Organizer</title>
    <style>
      body {
        margin: 0;
        background: #0d1522;
        color: #f3f6fc;
        font-family: "Segoe UI", sans-serif;
      }
      main {
        max-width: 760px;
        margin: 64px auto;
        padding: 32px;
        background: #172235;
        border: 1px solid #2b3a52;
        border-radius: 24px;
      }
      h1 { margin-top: 0; }
      code {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: #22324c;
      }
      pre {
        padding: 16px;
        border-radius: 16px;
        background: #111d2e;
        overflow-x: auto;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Frontend assets are not built yet</h1>
      <p>The FastAPI backend is running, but the React/Vite frontend has not been built into <code>web_static</code> yet.</p>
      <p>Use these commands in the repository root:</p>
      <pre>cd webui
npm install
npm run build</pre>
    </main>
  </body>
</html>
"""


@dataclass(slots=True)
class LauncherState:
    port: int = 0
    heartbeat_timeout_seconds: int = 45
    startup_grace_seconds: int = 120
    shutdown_requested: threading.Event = field(default_factory=threading.Event)
    heartbeat_seen: threading.Event = field(default_factory=threading.Event)
    _last_heartbeat: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()
            self.heartbeat_seen.set()

    def seconds_since_last_heartbeat(self) -> float | None:
        with self._lock:
            if self._last_heartbeat is None:
                return None
            return time.monotonic() - self._last_heartbeat


class DialogPathsResponse(BaseModel):
    paths: list[str] = Field(default_factory=list)


class DialogPathResponse(BaseModel):
    path: str | None = None


class StatsResponse(BaseModel):
    discovered_metadata: int
    discovered_media: int
    merged_files: int
    tagged_files: int
    skipped_files: int
    error_count: int
    errors: list[str]


class SummaryRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)


class MediaSummaryResponse(BaseModel):
    zip_count: int
    folder_count: int
    metadata_records: int
    total_media: int
    image_count: int
    video_count: int
    scan_complete: bool
    scan_ready: bool
    found_media_files: int
    matched_media_files: int
    missing_media_files: int
    orphan_media_files: int
    errors: list[str]
    warnings: list[str]


class JobCreateRequest(BaseModel):
    sources: list[str] = Field(default_factory=list)
    output_dir: str = ""


class JobCreateResponse(BaseModel):
    job_id: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    sources: list[str]
    output_dir: str
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    logs: list[str] = Field(default_factory=list)
    stats: StatsResponse | None = None
    error: str | None = None


class AppStateResponse(BaseModel):
    app_name: str
    version: str
    platform: str
    port: int
    frontend_ready: bool
    current_job_id: str | None = None


@dataclass
class JobRecord:
    job_id: str
    sources: list[str]
    output_dir: str
    created_at: str = field(default_factory=_utc_now)
    status: str = "queued"
    started_at: str | None = None
    ended_at: str | None = None
    logs: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    stats: ProcessStats | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._current_job_id: str | None = None

    def create_job(self, *, sources: list[str], output_dir: str) -> JobRecord:
        job = JobRecord(job_id=uuid.uuid4().hex, sources=sources, output_dir=output_dir)
        self._record_event(job, event_type="queued", payload={"status": job.status})
        with self._lock:
            self._jobs[job.job_id] = job
            self._current_job_id = job.job_id
        worker = threading.Thread(target=self._run_job, args=(job,), daemon=True, name=f"job-{job.job_id[:8]}")
        worker.start()
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def current_job_id(self) -> str | None:
        with self._lock:
            return self._current_job_id

    def serialize_job(self, job: JobRecord) -> JobResponse:
        with job.lock:
            return JobResponse(
                job_id=job.job_id,
                status=job.status,
                sources=list(job.sources),
                output_dir=job.output_dir,
                created_at=job.created_at,
                started_at=job.started_at,
                ended_at=job.ended_at,
                logs=list(job.logs),
                stats=_serialize_stats(job.stats),
                error=job.error,
            )

    def events_since(self, job: JobRecord, cursor: int) -> tuple[list[dict[str, Any]], bool]:
        with job.lock:
            return list(job.events[cursor:]), job.status in {"completed", "failed"}

    def _run_job(self, job: JobRecord) -> None:
        with job.lock:
            job.status = "running"
            job.started_at = _utc_now()
        self._record_event(job, event_type="status", payload={"status": "running"})

        try:
            stats = process_sources(
                sources=job.sources,
                output_dir=job.output_dir,
                status=lambda message: self._append_log(job, message),
            )
            with job.lock:
                job.status = "completed"
                job.ended_at = _utc_now()
                job.stats = stats
            self._record_event(
                job,
                event_type="completed",
                payload={"status": "completed", "stats": _serialize_stats(stats).model_dump()},
            )
        except Exception as exc:
            with job.lock:
                job.status = "failed"
                job.ended_at = _utc_now()
                job.error = str(exc)
            self._record_event(job, event_type="failed", payload={"status": "failed", "error": str(exc)})

    def _append_log(self, job: JobRecord, message: str) -> None:
        with job.lock:
            job.logs.append(message)
        self._record_event(job, event_type="log", payload={"message": message})

    def _record_event(self, job: JobRecord, *, event_type: str, payload: dict[str, Any]) -> None:
        with job.lock:
            job.events.append(
                {
                    "id": len(job.events) + 1,
                    "type": event_type,
                    "timestamp": _utc_now(),
                    **payload,
                }
            )


def _serialize_stats(stats: ProcessStats | None) -> StatsResponse | None:
    if stats is None:
        return None
    return StatsResponse(
        discovered_metadata=stats.discovered_metadata,
        discovered_media=stats.discovered_media,
        merged_files=stats.merged_files,
        tagged_files=stats.tagged_files,
        skipped_files=stats.skipped_files,
        error_count=len(stats.errors),
        errors=list(stats.errors),
    )


def _serialize_summary(summary: MediaSummary) -> MediaSummaryResponse:
    return MediaSummaryResponse(
        zip_count=summary.zip_count,
        folder_count=summary.folder_count,
        metadata_records=summary.metadata_records,
        total_media=summary.total_media,
        image_count=summary.image_count,
        video_count=summary.video_count,
        scan_complete=summary.scan_complete,
        scan_ready=summary.scan_ready,
        found_media_files=summary.found_media_files,
        matched_media_files=summary.matched_media_files,
        missing_media_files=summary.missing_media_files,
        orphan_media_files=summary.orphan_media_files,
        errors=list(summary.errors),
        warnings=list(summary.warnings),
    )


def create_app(launcher_state: LauncherState | None = None) -> FastAPI:
    state = launcher_state or LauncherState()
    jobs = JobManager()
    app = FastAPI(title="Snapchat Export Organizer")
    app.state.launcher_state = state
    app.state.jobs = jobs

    assets_dir = _static_dir() / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/api/app-state", response_model=AppStateResponse)
    def app_state() -> AppStateResponse:
        return AppStateResponse(
            app_name="Snapchat Export Organizer",
            version=_package_version(),
            platform=platform.system(),
            port=state.port,
            frontend_ready=_index_path().exists(),
            current_job_id=jobs.current_job_id(),
        )

    @app.post("/api/dialog/select-zips", response_model=DialogPathsResponse)
    def api_select_zips() -> DialogPathsResponse:
        try:
            return DialogPathsResponse(paths=select_zip_files())
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/dialog/select-folder", response_model=DialogPathResponse)
    def api_select_folder() -> DialogPathResponse:
        try:
            return DialogPathResponse(path=select_folder("Select a Snapchat export folder"))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/dialog/select-output", response_model=DialogPathResponse)
    def api_select_output() -> DialogPathResponse:
        try:
            return DialogPathResponse(path=select_folder("Select output folder"))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/analysis/summary", response_model=MediaSummaryResponse)
    def api_summary(payload: SummaryRequest) -> MediaSummaryResponse:
        sources = [item.strip() for item in payload.sources if item.strip()]
        if not sources:
            raise HTTPException(status_code=400, detail="Please add at least one ZIP file or folder.")
        summary = analyze_sources(sources=sources)
        return _serialize_summary(summary)

    @app.post("/api/jobs", response_model=JobCreateResponse, status_code=201)
    def api_create_job(payload: JobCreateRequest) -> JobCreateResponse:
        sources = [item.strip() for item in payload.sources if item.strip()]
        output_dir = payload.output_dir.strip()
        if not sources:
            raise HTTPException(status_code=400, detail="Please add at least one ZIP file or folder.")
        if not output_dir:
            raise HTTPException(status_code=400, detail="Please choose an output folder.")

        job = jobs.create_job(sources=sources, output_dir=output_dir)
        return JobCreateResponse(job_id=job.job_id)

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def api_get_job(job_id: str) -> JobResponse:
        job = jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return jobs.serialize_job(job)

    @app.get("/api/jobs/{job_id}/events")
    async def api_job_events(job_id: str) -> StreamingResponse:
        job = jobs.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")

        async def stream() -> Any:
            cursor = 0
            while True:
                events, finished = jobs.events_since(job, cursor)
                if events:
                    for event in events:
                        cursor += 1
                        yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                elif finished:
                    break
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.35)
            yield "event: close\ndata: {}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/heartbeat", status_code=204)
    def api_heartbeat() -> Response:
        state.mark_heartbeat()
        return Response(status_code=204)

    @app.post("/api/shutdown", status_code=202)
    def api_shutdown() -> dict[str, str]:
        state.shutdown_requested.set()
        return {"status": "shutting-down"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> Response:
        if _index_path().exists():
            return FileResponse(_index_path())
        return HTMLResponse(FALLBACK_HTML)

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def spa_fallback(full_path: str) -> Response:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        if _index_path().exists():
            return FileResponse(_index_path())
        return HTMLResponse(FALLBACK_HTML)

    return app
