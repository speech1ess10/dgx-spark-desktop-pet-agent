"""FastAPI entry point for the DGX Spark desktop pet agent."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .core import AssetCatalog, DesktopPetAgent
from .generation import GenerationManager


def default_asset_dir() -> Path:
    configured = os.environ.get("PET_ASSET_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "output" / "red-scarf-cat-final"


catalog = AssetCatalog(default_asset_dir())
agent = DesktopPetAgent(catalog)
package_root = Path(__file__).resolve().parents[1]
jobs = GenerationManager(
    root=Path(os.environ.get("PET_JOBS_DIR", str(Path.home() / "desktop-pet-agent-data" / "jobs"))),
    qwen_workflow=Path(
        os.environ.get(
            "PET_QWEN_WORKFLOW",
            str(package_root / "workflows" / "qwen_image_edit_api.json"),
        )
    ),
    wan_workflow=Path(
        os.environ.get(
            "PET_WAN_WORKFLOW", str(package_root / "workflows" / "wan22_i2v_api.json")
        )
    ),
    activate=agent.replace_catalog,
    comfy_server=os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188"),
)

app = FastAPI(
    title="DGX Spark Desktop Pet Agent",
    version="0.1.0",
    description="Desktop companion state and asset service.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class CommandRequest(BaseModel):
    text: str = Field(default="", max_length=500)
    action: str | None = Field(default=None, max_length=40)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    reference_image_base64: str
    reference_filename: str = Field(default="reference.png", max_length=200)
    actions: list[str] = ["yawn", "sleep", "eat"]


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "desktop-pet-agent",
        "actions": list(agent.catalog.actions),
        "asset_dir": str(agent.catalog.asset_dir),
        "generation_enabled": True,
    }


@app.get("/api/v1/pet")
def get_pet() -> dict:
    return agent.snapshot()


@app.post("/api/v1/command")
def command(request: CommandRequest) -> dict:
    if not request.text.strip() and not request.action:
        raise HTTPException(status_code=400, detail="text 或 action 至少提供一个")
    return agent.command(text=request.text, action=request.action)


@app.post("/api/v1/poke")
def poke() -> dict:
    return agent.poke()


@app.get("/api/v1/assets/{action}")
def asset(action: str) -> FileResponse:
    try:
        path = agent.catalog.gif_path(action)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, media_type="image/gif", filename=path.name)


@app.post("/api/v1/generate", status_code=202)
def generate(request: GenerateRequest) -> dict:
    try:
        return jobs.create(
            prompt=request.prompt,
            reference_b64=request.reference_image_base64,
            reference_name=request.reference_filename,
            actions=request.actions,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
