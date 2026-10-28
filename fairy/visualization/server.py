"""HTTP and WebSocket boundary for the local farm workbench."""
from __future__ import annotations

import asyncio
import json
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewRun(Input):
    scenario_id: StrictStr | None = None
    seed: Annotated[StrictInt, Field(ge=0, le=0)] = 0


class Command(Input):
    command_id: Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
    tool: Annotated[StrictStr, Field(min_length=1, max_length=160)]
    args: dict[str, Any] = Field(default_factory=dict)

    @field_validator("args")
    @classmethod
    def finite_json(cls, value):
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("Arguments must be finite JSON values") from exc
        if len(encoded) > 65536:
            raise ValueError("Arguments exceed 64 KiB")
        return value


class Control(Input):
    mode: Literal["external", "llm"]
    controller_id: Annotated[StrictStr, Field(min_length=1, max_length=128)] | None = None
    task: Annotated[StrictStr, Field(min_length=1, max_length=8000)] | None = None


class Binding(Input):
    kind: Literal["farm", "device", "sensor"]
    farm_id: StrictStr | None = None
    asset_id: StrictStr | None = None


class VisualObject(Input):
    visual_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    binding: Binding
    label: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    model_url: StrictStr | None = None

    @field_validator("position", "rotation")
    @classmethod
    def finite_transform(cls, value):
        if any(not math.isfinite(x) or abs(x) > 10000 for x in value):
            raise ValueError("Transform must contain finite bounded values")
        return value

    @field_validator("model_url")
    @classmethod
    def local_glb(cls, value):
        if value is not None:
            import re
            if not re.fullmatch(r"/models/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.glb", value):
                raise ValueError("Use a packaged /models/*.glb asset")
        return value


class Layout(Input):
    schema_version: Literal[1] = 1
    objects: Annotated[list[VisualObject], Field(max_length=200)]


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix, sep, token = authorization.partition(" ")
    if prefix.lower() != "bearer" or not sep or not token:
        raise HTTPException(401, detail={"code": "invalid_controller_token", "message": "Expected a Bearer controller token"})
    return token


def create_app(data_dir: str | Path | None = None, *, manager=None, web_dist: str | Path | None = None) -> FastAPI:
    """Create an app; injection is available for isolated boundary tests."""
    from .runner import ManagerError, WorkbenchManager

    @asynccontextmanager
    async def lifespan(app):
        if manager is not None:
            app.state.manager = manager
        else:
            directory = Path(data_dir or os.environ.get("FAIRY_VIS_DATA", str(Path.cwd().parent / "farm-runs")))
            app.state.manager = WorkbenchManager(directory)
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.manager.close)

    app = FastAPI(title="FAIRY Farm Workbench", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(ManagerError)
    async def manager_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": {"code": exc.code, "message": str(exc)}})

    @app.exception_handler(ModuleNotFoundError)
    async def dependency_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": {"code": "missing_dependency", "message": "Install the visualization and wofost dependencies before starting an experiment."}})

    async def call(method: str, *args, **kwargs):
        return await asyncio.to_thread(getattr(app.state.manager, method), *args, **kwargs)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "schema_version": 1}

    @app.get("/api/catalog")
    async def catalog():
        return await call("catalog")

    @app.get("/api/runs")
    async def runs():
        result = await call("list_runs")
        return result if isinstance(result, dict) else {"runs": result}

    @app.post("/api/runs", status_code=201)
    async def create_run(payload: NewRun):
        kwargs = {"seed": payload.seed}
        if payload.scenario_id is not None:
            kwargs["scenario_id"] = payload.scenario_id
        return await call("create_run", **kwargs)

    @app.get("/api/runs/current")
    async def current():
        return await call("current")

    @app.get("/api/runs/{run_id}/snapshot")
    async def snapshot(run_id: str):
        return await call("snapshot", run_id)

    @app.get("/api/runs/{run_id}/tools")
    async def tool_catalog(run_id: str):
        result = await call("tools", run_id)
        return result if isinstance(result, dict) else {"tools": result}

    @app.post("/api/runs/{run_id}/commands", status_code=202)
    async def submit(run_id: str, payload: Command, request: Request):
        return await call("submit", run_id, payload.command_id, payload.tool, payload.args, token=_bearer(request.headers.get("authorization")))

    @app.get("/api/runs/{run_id}/commands/{command_id}")
    async def command(run_id: str, command_id: str):
        return await call("command", run_id, command_id)

    @app.get("/api/runs/{run_id}/history")
    async def history(run_id: str):
        result = await call("history", run_id)
        return result if isinstance(result, dict) else {"frames": result}

    @app.get("/api/runs/{run_id}/history/{revision}")
    async def historical(run_id: str, revision: int):
        return await call("snapshot", run_id, revision=revision)

    @app.get("/api/runs/{run_id}/observations")
    async def observations(run_id: str, revision: int | None = None):
        return await call("observations", run_id, revision=revision)

    @app.get("/api/runs/{run_id}/audit")
    async def audit(run_id: str, revision: int | None = None):
        return await call("audit", run_id, revision=revision)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str):
        result = await call("events", run_id)
        return result if isinstance(result, dict) else {"events": result}

    @app.post("/api/runs/{run_id}/controller")
    async def controller(run_id: str, payload: Control):
        if payload.mode == "external":
            if not payload.controller_id or payload.task is not None:
                raise HTTPException(422, detail={"code": "invalid_request", "message": "External mode needs controller_id and no task"})
            return await call("acquire_external", run_id, payload.controller_id)
        if not payload.task or payload.controller_id is not None:
            raise HTTPException(422, detail={"code": "invalid_request", "message": "LLM mode needs task and no controller_id"})
        result = await call("start_agent", run_id, payload.task)
        return result if "snapshot" in result else {"snapshot": result}

    @app.post("/api/runs/{run_id}/stop")
    async def stop(run_id: str, request: Request):
        return await call("stop", run_id, token=_bearer(request.headers.get("authorization")))

    @app.post("/api/runs/{run_id}/reset")
    async def reset(run_id: str):
        return await call("reset", run_id)

    @app.get("/api/runs/{run_id}/layout")
    async def get_layout(run_id: str):
        return await call("get_layout", run_id)

    @app.put("/api/runs/{run_id}/layout")
    async def save_layout(run_id: str, payload: Layout):
        value = payload.model_dump(mode="json", exclude_none=True)
        for row, original in zip(value["objects"], payload.objects):
            row["model_url"] = original.model_url
        return await call("save_layout", run_id, value)

    @app.get("/api/compare")
    async def compare(left: str, right: str):
        return await call("compare", left, right)

    @app.websocket("/api/runs/{run_id}/stream")
    async def stream(websocket: WebSocket, run_id: str):
        await websocket.accept()
        previous = None
        try:
            while True:
                frame = await call("snapshot", run_id)
                signature = json.dumps(frame, sort_keys=True, allow_nan=False)
                if signature != previous:
                    await websocket.send_json({"type": "snapshot", "snapshot": frame})
                    previous = signature
                if frame.get("status") in {"archived", "interrupted", "closed"}:
                    await websocket.close(code=1000)
                    return
                await asyncio.sleep(0.3)
        except WebSocketDisconnect:
            return
        except ManagerError as exc:
            await websocket.close(code=1008, reason=exc.code[:100])

    # Register the SPA last so API paths keep their JSON contract.
    dist = Path(web_dist) if web_dist is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    if (dist / "models").is_dir():
        app.mount("/models", StaticFiles(directory=dist / "models"), name="models")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith(("api/", "models/", "assets/")):
            raise HTTPException(404, "Not found")
        if (dist / "index.html").is_file():
            candidate = (dist / path).resolve()
            if path and candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
        return JSONResponse(status_code=503, content={"message": "Frontend not built. In web install dependencies (npm install initially; npm ci with a lockfile), run npm run build, then start the workbench again."})

    return app
