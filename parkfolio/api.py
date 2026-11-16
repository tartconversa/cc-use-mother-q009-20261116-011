from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .batch import Batch
from .model import Conflict, DomainError, MissingReference
from .service import Parkfolio


class SourceInput(BaseModel):
    name: str
    enabled: bool = True


class StoreInput(BaseModel):
    store_id: str
    name: str
    park: str


class SpaceInput(BaseModel):
    space_id: str
    store_id: str
    kind: str
    capacity: int
    valid_from: str
    valid_until: str | None = None


class BookInput(BaseModel):
    book_id: str
    title: str
    topic: str
    store_id: str


class ProgramInput(BaseModel):
    program_id: str
    store_id: str
    space_id: str
    starts_at: str
    ends_at: str
    title: str
    capacity: int


class EventInput(BaseModel):
    source: str
    external_id: str
    kind: str
    occurred_at: str
    received_at: str
    payload: dict


class ReleaseInput(BaseModel):
    name: str
    month: str
    expected_fingerprint: str


class BatchInput(BaseModel):
    batch_id: str
    events: list[dict]
    stop_after: int | None = None


def create_app(path: str | None = None) -> FastAPI:
    service = Parkfolio(path or os.environ.get("PARKFOLIO_DB", "parkfolio.sqlite3"))
    batch = Batch(service)
    app = FastAPI(title="Parkfolio", version="1.0.0")
    app.state.service = service
    app.state.batch = batch

    @app.exception_handler(DomainError)
    async def domain_exception(_, exc: DomainError):
        from fastapi.responses import JSONResponse
        status = 404 if isinstance(exc, MissingReference) else (409 if isinstance(exc, Conflict) else 422)
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok", "overview": service.overview()}

    @app.post("/sources")
    def put_source(value: SourceInput):
        return service.events.source(value.name, value.enabled)

    @app.get("/sources")
    def sources():
        return service.quality.source_health()

    @app.post("/stores")
    def put_store(value: StoreInput):
        return service.spaces.put_store(**value.model_dump())

    @app.get("/stores")
    def stores():
        return service.spaces.list_stores()

    @app.post("/spaces")
    def put_space(value: SpaceInput):
        return service.spaces.put_space(**value.model_dump())

    @app.get("/spaces")
    def spaces(store_id: str | None = None):
        return service.spaces.list_spaces(store_id)

    @app.post("/books")
    def put_book(value: BookInput):
        return service.catalog.put(**value.model_dump())

    @app.get("/books")
    def books(store_id: str | None = None, active_only: bool = False):
        return service.catalog.list(store_id, active_only)

    @app.post("/programs")
    def put_program(value: ProgramInput):
        return service.programs.put(**value.model_dump())

    @app.get("/programs")
    def programs(store_id: str | None = None):
        return service.programs.list(store_id)

    @app.get("/programs/{program_id}/attendance")
    def attendance(program_id: str):
        return service.attendance.status(program_id)

    @app.post("/events")
    def accept(value: EventInput):
        return service.events.accept(value.model_dump())

    @app.post("/events/{event_id}/retry")
    def retry(event_id: int):
        return service.events.retry(event_id)

    @app.get("/events/{event_id}")
    def event(event_id: int):
        return service.quality.lineage(event_id)

    @app.get("/events")
    def events(status: str | None = None, month: str | None = None):
        return service.events.list(status, month)

    @app.post("/batches")
    def load(value: BatchInput):
        return batch.load(value.batch_id, value.events, stop_after=value.stop_after)

    @app.get("/batches/{batch_id}")
    def batch_status(batch_id: str):
        return batch.status(batch_id)

    @app.get("/quality/{month}")
    def quality(month: str):
        return service.quality.period(month)

    @app.get("/mart/{month}")
    def mart(month: str):
        return service.mart.period(month)

    @app.get("/mart/{month}/{store_id}")
    def store_mart(month: str, store_id: str):
        return service.mart.store_month(store_id, month)

    @app.get("/analysis/{month}/{store_id}/funnel")
    def funnel(month: str, store_id: str):
        return service.analysis.reading_funnel(month, store_id)

    @app.get("/analysis/{month}/{store_id}/topics")
    def topics(month: str, store_id: str):
        return service.analysis.topic_mix(month, store_id)

    @app.get("/analysis/{month}/{store_id}/spaces")
    def space_use(month: str, store_id: str):
        return service.analysis.space_use(month, store_id)

    @app.get("/analysis/{month}/{store_id}/revenue")
    def revenue(month: str, store_id: str):
        return service.analysis.revenue_bridge(month, store_id)

    @app.get("/visits/{visit_id}/lineage")
    def visit_lineage(visit_id: str):
        return service.audit.visit(visit_id)

    @app.get("/audit/{month}/sources")
    def month_sources(month: str):
        return service.audit.month_sources(month)

    @app.get("/audit/releases/{name}/events/{event_id}")
    def release_source(name: str, event_id: int):
        return service.audit.release_source(name, event_id)

    @app.get("/consistency/{month}/{store_id}")
    def consistency(month: str, store_id: str):
        return service.consistency.check_store(store_id, month)

    @app.get("/daily/{month}/{store_id}/receipts")
    def receipts(month: str, store_id: str):
        return service.consistency.receipts_by_day(store_id, month)

    @app.get("/daily/{month}/{store_id}/occupancy")
    def occupancy(month: str, store_id: str):
        return service.consistency.occupancy_by_day(store_id, month)

    @app.get("/export/{month}/csv", response_class=PlainTextResponse)
    def export_csv(month: str):
        return service.exports.month_csv(month)

    @app.get("/export/{month}/explain")
    def export_explain(month: str):
        return service.exports.explain(month)

    @app.get("/compare/{store_id}/{first}/{second}")
    def compare_months(store_id: str, first: str, second: str):
        return service.compare.months(store_id, first, second)

    @app.get("/compare/release/{name}/current")
    def compare_release(name: str):
        return service.compare.release_to_current(name)

    @app.get("/releases/preview/{month}")
    def preview(month: str):
        return service.releases.preview(month)

    @app.post("/releases")
    def publish(value: ReleaseInput):
        return service.releases.publish(value.name, value.month, value.expected_fingerprint)

    @app.get("/releases")
    def releases():
        return service.releases.list()

    @app.get("/releases/{name}")
    def release(name: str):
        return service.releases.get(name)

    return app


app = create_app()
