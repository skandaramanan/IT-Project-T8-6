"""Loopback FastAPI boundary and plain integration page for the review service."""

import math
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from survey.records import REGION, RecordStore, ReviewError, safe_pdf
from survey.review.queue import load_queue
from survey.review.scans import LocalScanSource
from survey.review.service import ReviewService
from survey.review.sync import GitSync

FRONTEND_DIST = Path(__file__).parents[3] / "frontend" / "dist"


@dataclass(frozen=True)
class Settings:
    scan_root: Path
    data_checkout: Path
    flags: Path
    cache: Path
    data_branch: str = "review-data"
    sync_interval: float = 180
    port: int = 8765

    def validate(self):
        code_root = Path(__file__).parents[3].resolve()
        checkout, cache = self.data_checkout.resolve(), self.cache.resolve()
        if checkout == code_root or checkout.is_relative_to(code_root):
            raise ReviewError(
                "invalid_checkout",
                "Use a separate data checkout outside the code checkout",
            )
        if cache.is_relative_to(checkout) or cache.is_relative_to(code_root):
            raise ReviewError(
                "invalid_cache", "Scan cache must be outside both Git checkouts"
            )
        if not self.scan_root.is_dir():
            raise ReviewError(
                "missing_scans",
                "Configure an existing scan root containing region folders",
            )
        if (checkout / "results").is_symlink():
            raise ReviewError(
                "invalid_results",
                "Results must be a real directory inside the data checkout",
            )
        if not (checkout / "results").is_dir():
            raise ReviewError(
                "missing_results", "Data checkout must contain results/<region>.jsonl"
            )
        if (
            not 1 <= self.port <= 65535
            or not math.isfinite(self.sync_interval)
            or self.sync_interval <= 0
        ):
            raise ReviewError(
                "invalid_settings", "Port and synchronization interval must be positive"
            )


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionBody(Body):
    name: str = Field(min_length=1, max_length=100)


class VersionedBody(Body):
    expected_version: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=128)


class DecisionBody(VersionedBody):
    action: Literal["accept", "correct", "no_data", "illegible"]
    value: str | None = None


def error_response(code, message, status):
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status
    )


def create_app(settings: Settings) -> FastAPI:
    sessions = {}
    stop = Event()
    worker = None
    startup_error = None
    service = sync = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal service, sync, worker, startup_error
        try:
            settings.validate()
            store = RecordStore(settings.data_checkout / "results", load=False)
            sync = GitSync(settings.data_checkout, store, settings.data_branch)
            sync.writer_lock.acquire()
            store.reload()
            refs, diagnostics = load_queue(settings.flags)
            service = ReviewService(
                store,
                refs,
                diagnostics,
                LocalScanSource(settings.scan_root, settings.cache),
            )
            if not store.regions:
                raise ReviewError(
                    "missing_records",
                    "Supply extracted region JSONL in the separate data checkout",
                )
            if not refs and not diagnostics:
                raise ReviewError(
                    "empty_flags", "Flagged file is empty; supply teammate flags"
                )
            app.state.service, app.state.sync = service, sync

            def periodic():
                while not stop.wait(settings.sync_interval):
                    sync.sync(service.reindex_history)

            worker = Thread(target=periodic, daemon=True, name="review-sync")
            worker.start()
        except (ReviewError, OSError, subprocess.SubprocessError) as error:
            startup_error = {
                "code": getattr(error, "code", "startup_failed"),
                "message": str(error)
                if isinstance(error, ReviewError)
                else "Startup I/O or Git failed; inspect paths and Git configuration",
            }
        try:
            yield
        finally:
            stop.set()
            if worker:
                worker.join()
            if sync:
                sync.writer_lock.release()

    app = FastAPI(title="Survey review backend", version="0.4.0", lifespan=lifespan)

    @app.exception_handler(ReviewError)
    async def domain_error(request, error):
        return error_response(error.code, str(error), error.status)

    @app.exception_handler(RequestValidationError)
    async def input_error(request, error):
        return error_response(
            "invalid_input", "Request does not match the API schema; see /docs", 422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            "not_found" if error.status_code == 404 else "http_error",
            str(error.detail),
            error.status_code,
        )

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        hosts = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
        if request.headers.get("host") not in hosts:
            return error_response(
                "unexpected_host", "Use the configured loopback address", 403
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origins = {f"http://{host}" for host in hosts}
            origin = request.headers.get("origin")
            if (origin is not None and origin not in origins) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return error_response(
                    "unexpected_origin",
                    "Mutations require the local same-origin page",
                    403,
                )
            if (
                request.headers.get("content-type", "").split(";")[0]
                != "application/json"
            ):
                return error_response(
                    "invalid_content_type", "Send application/json", 422
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def ready():
        if startup_error or service is None:
            raise ReviewError(
                "not_ready",
                (startup_error or {}).get("message", "Backend is starting"),
                503,
            )
        return service

    def reviewer(request: Request):
        name = sessions.get(request.cookies.get("review_session"))
        if not name:
            raise ReviewError(
                "missing_session", "Enter your reviewer name before saving", 401
            )
        return name

    @app.get("/api/health")
    def health():
        return {
            "ready": startup_error is None and service is not None,
            "diagnostics": [startup_error] if startup_error else [],
            "scope": "C1/C2 numeric flagged fields; one backend writer per checkout",
            "data_branch": settings.data_branch,
        }

    @app.post("/api/session")
    def session(body: SessionBody, response: Response):
        ready()
        name = body.name.strip()
        if not name:
            raise ReviewError("invalid_reviewer", "Reviewer name cannot be blank")
        token = str(uuid4())
        sessions[token] = name
        response.set_cookie("review_session", token, httponly=True, samesite="strict")
        return {"reviewer": name, "identity": "typed name; unverified"}

    @app.get("/api/regions")
    def regions():
        review = ready()
        regions = sorted(
            set(review.store.regions)
            | {ref.region for ref in review.references.values()}
            | {
                d["region"]
                for d in review.diagnostics
                if isinstance(d.get("region"), str) and REGION.fullmatch(d["region"])
            }
        )
        return {
            "regions": [
                {
                    "region": region,
                    "title": review.region_titles.get(region) or None,
                    "has_records": region in review.store.regions,
                    "has_scan_folder": (settings.scan_root / region).is_dir(),
                    "batches": sorted(
                        {
                            ref.pdf
                            for ref in review.references.values()
                            if ref.region == region
                        }
                        | {
                            d["batch"]
                            for d in review.diagnostics
                            if d.get("region") == region
                            and isinstance(d.get("batch"), str)
                            and safe_pdf(d["batch"])
                        }
                    ),
                }
                for region in regions
            ]
        }

    @app.get("/api/dwellings")
    def dwellings(region: str | None = None):
        return ready().dwellings(region)

    @app.get("/api/dwellings/{dwelling_id}/items")
    def dwelling_items(dwelling_id: str, region: str | None = None):
        return ready().dwelling_items(dwelling_id, region)

    @app.get("/api/queue")
    def queue(region: str | None = None, batch: str | None = None):
        return ready().queue(region, batch)

    @app.get("/api/review-items/{item_id}")
    def item(item_id: str):
        return ready().item(item_id)

    @app.get("/api/review-items/{item_id}/history")
    def history(item_id: str):
        return {
            "history": ready()
            .item(item_id)["field"]
            .get("review", {})
            .get("history", [])
        }

    @app.get("/api/scans/{card_id}")
    def scan(card_id: str):
        review = ready()
        ref = next(
            (r for r in review.references.values() if r.card_id == card_id), None
        )
        if ref is None:
            raise ReviewError("missing_scan", "Unknown physical card", 404)
        review.store.current(ref)
        return FileResponse(review.scans.get_scan(ref), media_type="image/png")

    def completion_sync(item):
        if service.batch_complete(item["region"], item["batch"]):
            sync.sync(service.reindex_history)

    @app.post("/api/review-items/{item_id}/decisions")
    def decision(item_id: str, body: DecisionBody, request: Request):
        review = ready()
        with review.store.lock:
            sync.verify_checkout()
            result = review.apply_decision(
                item_id,
                body.action,
                reviewer(request),
                body.expected_version,
                body.request_id,
                body.value,
            )
        completion_sync(result["item"])
        result["sync"] = sync.status()
        return result

    @app.post("/api/decisions/{decision_id}/undo")
    def undo(decision_id: str, body: VersionedBody, request: Request):
        review = ready()
        with review.store.lock:
            sync.verify_checkout()
            result = review.undo_latest(
                decision_id, reviewer(request), body.expected_version, body.request_id
            )
        result["sync"] = sync.status()
        return result

    @app.get("/api/sync/status")
    def sync_status():
        ready()
        return sync.status()

    @app.post("/api/sync")
    def synchronize(request: Request):
        ready()
        reviewer(request)
        return sync.sync(service.reindex_history)

    static = (
        FRONTEND_DIST
        if (FRONTEND_DIST / "index.html").is_file()
        else Path(__file__).with_name("static")
    )
    app.mount("/", StaticFiles(directory=static, html=True), name="review-page")
    return app
