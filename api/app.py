"""REST and WebSocket API for synthetic EnergySense Twin runs."""

import asyncio
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

from api.service import APIService
from contracts.models import (
    AnomalyResponse,
    CopilotRequest,
    CopilotResponse,
    ForecastResponse,
    KPIResponse,
    RecommendationDecision,
    RecommendationScheduleRequest,
    ReportResponse,
    RunRequest,
    RunResponse,
    WhatIfRequest,
    WhatIfResponse,
)


def create_app(service: APIService | None = None) -> FastAPI:
    data_dir = Path(os.getenv("ENERGYSENSE_DATA_DIR", "data/generated"))
    report_dir = Path(os.getenv("ENERGYSENSE_REPORT_DIR", "reports/api"))
    twin_service = service or APIService(data_dir, report_dir)
    app = FastAPI(title="EnergySense Twin API", version="0.1.0")
    app.state.twin_service = twin_service

    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except FileNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/scenarios")
    def get_scenarios() -> list[dict[str, Any]]:
        return twin_service.scenarios()

    @app.post("/run", response_model=RunResponse)
    def run_scenario(request: RunRequest) -> Any:
        return call(twin_service.run, request)

    @app.get("/kpis", response_model=KPIResponse)
    def get_kpis(day: Annotated[date | None, Query(alias="date")] = None) -> Any:
        return call(twin_service.kpis, day)

    @app.get("/recommendations")
    def get_recommendations(mode: str = Query(default="human", pattern="^(human|auto)$")) -> Any:
        return call(twin_service.recommendations, mode)

    @app.post("/recommendations/{recommendation_id}/apply", response_model=RecommendationDecision)
    def apply_recommendation(recommendation_id: str) -> Any:
        return call(twin_service.decide, recommendation_id, "approved")

    @app.post("/recommendations/{recommendation_id}/reject", response_model=RecommendationDecision)
    def reject_recommendation(recommendation_id: str) -> Any:
        return call(twin_service.decide, recommendation_id, "rejected")

    @app.post(
        "/recommendations/{recommendation_id}/schedule", response_model=RecommendationDecision
    )
    def schedule_recommendation(
        recommendation_id: str, request: RecommendationScheduleRequest
    ) -> Any:
        return call(twin_service.decide, recommendation_id, "scheduled", request.scheduled_for)

    @app.post("/what-if", response_model=WhatIfResponse)
    def what_if(request: WhatIfRequest) -> Any:
        return call(twin_service.what_if, request)

    @app.get("/forecast", response_model=ForecastResponse)
    def forecast(horizon_steps: int = Query(default=4, ge=1, le=24)) -> Any:
        return call(twin_service.forecast, horizon_steps)

    @app.get("/anomalies", response_model=AnomalyResponse)
    def anomalies(
        threshold_kw: float = Query(default=35.0, gt=0),
        day: Annotated[date | None, Query(alias="date")] = None,
    ) -> Any:
        return call(twin_service.anomalies, threshold_kw, day)

    @app.get("/cv/events")
    def cv_events(
        day: Annotated[date | None, Query(alias="date")] = None,
        limit: int = Query(default=1000, ge=1, le=5000),
    ) -> Any:
        return call(twin_service.cv_events, day, limit)

    @app.get("/report", response_model=ReportResponse)
    def report() -> Any:
        return call(twin_service.report)

    @app.post("/copilot", response_model=CopilotResponse)
    def copilot(request: CopilotRequest) -> Any:
        try:
            return twin_service.copilot().ask(request.query)
        except FileNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.websocket("/ws/replay")
    async def replay(websocket: WebSocket) -> None:
        await websocket.accept()
        speed = 1
        paused = False
        policy = "baseline"
        recommendations: list[dict[str, Any]] = []
        scenario = twin_service._manifest().get("scenario", "S1")
        try:
            frames = twin_service.replay_events()
            await websocket.send_json(
                {"type": "ready", "frames": len(frames), "scenario": scenario, "synthetic": True}
            )
            index = 0
            while index < len(frames):
                if paused:
                    timeout = 0.25
                else:
                    timeout = 60.0 / speed
                try:
                    command = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
                    kind = command.get("type")
                    if kind == "pause":
                        paused = bool(command.get("value", True))
                    elif kind == "speed":
                        value = int(command.get("value", 1))
                        if value not in {1, 10, 60}:
                            await websocket.send_json(
                                {"type": "error", "detail": "speed must be 1, 10, or 60"}
                            )
                        else:
                            speed = value
                    elif kind == "seek":
                        target = command.get("timestamp")
                        if isinstance(target, str):
                            sought = datetime.fromisoformat(target)
                            index = next(
                                (
                                    position
                                    for position, frame in enumerate(frames)
                                    if frame["timestamp"] >= sought
                                ),
                                len(frames) - 1,
                            )
                        else:
                            index = max(0, min(len(frames) - 1, int(command.get("index", 0))))
                    elif kind == "policy":
                        value = command.get("value")
                        if value not in {"baseline", "ai"}:
                            await websocket.send_json(
                                {"type": "error", "detail": "policy must be baseline or ai"}
                            )
                        else:
                            policy = value
                            recommendations = (
                                call(twin_service.recommendations).get("recommendations", [])
                                if policy == "ai"
                                else []
                            )
                    elif kind == "scenario":
                        manifest = twin_service._manifest()
                        run = RunRequest(
                            scenario=str(command.get("value", "")),
                            seed=int(manifest.get("seed", 42)),
                            days=1,
                        )
                        result = call(twin_service.run, run)
                        scenario = run.scenario
                        frames = twin_service.replay_events()
                        index = 0
                        recommendations = (
                            call(twin_service.recommendations).get("recommendations", [])
                            if policy == "ai"
                            else []
                        )
                        await websocket.send_json(
                            {
                                "type": "scenario",
                                "value": scenario,
                                "output_dir": result["output_dir"],
                            }
                        )
                    else:
                        await websocket.send_json(
                            {"type": "error", "detail": "unknown replay command"}
                        )
                except TimeoutError:
                    if paused:
                        continue
                    frame = dict(frames[index])
                    stamp = frame["timestamp"]
                    frame["recommendations"] = [
                        rec
                        for rec in recommendations
                        if datetime.fromisoformat(str(rec["start"]))
                        <= stamp
                        < datetime.fromisoformat(str(rec["start"])) + timedelta(minutes=1)
                    ]
                    await websocket.send_json(
                        jsonable_encoder(
                            {
                                "type": "frame",
                                "policy": policy,
                                "scenario": scenario,
                                "synthetic": True,
                                "frame": frame,
                            }
                        )
                    )
                    index += 1
            await websocket.send_json({"type": "complete", "synthetic": True})
        except WebSocketDisconnect:
            return
        except (FileNotFoundError, ValueError) as error:
            await websocket.send_json({"type": "error", "detail": str(error)})
            await websocket.close(code=1008)
        except HTTPException as error:
            await websocket.send_json({"type": "error", "detail": error.detail})
            await websocket.close(code=1008)

    return app


app = create_app()
