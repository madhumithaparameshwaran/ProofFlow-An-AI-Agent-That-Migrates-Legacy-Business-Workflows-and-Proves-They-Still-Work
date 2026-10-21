from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from lxml import etree
from . import mapper
import re
from .pipeline import run_pipeline
from .evidence import build_run, save, RUNS

BASE = Path(__file__).parent
app = FastAPI(title="ProofFlow")


class RunReq(BaseModel):
    xml: str
    inject_bugs: bool = True
    filename: str = ""


@app.get("/api/sample", response_class=PlainTextResponse)
def sample():
    return (BASE / "sample.xml").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    return {"mode": mapper.mode()}


@app.post("/api/run")
def run(r: RunReq):
    try:
        result = run_pipeline(r.xml, r.inject_bugs)
        run = build_run(r.xml, r.filename, r.inject_bugs, result)
        save(run, result)
        return {**result, "run": run}
    except etree.XMLSyntaxError as e:
        raise HTTPException(400, f"The XML is not well-formed: {e}")
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"Unsupported or incomplete workflow definition: {e}")


@app.get("/")
def index():
    return FileResponse(BASE.parent / "static" / "index.html")


@app.get("/api/runs/{run_id}")
def download_run(run_id: str):
    if not re.fullmatch(r"run_[0-9_]+", run_id) or not (RUNS / f"{run_id}.json").exists():
        raise HTTPException(404, "Run not found")
    return FileResponse(RUNS / f"{run_id}.json", media_type="application/json", filename=f"{run_id}.json")
