import os, pathlib
import pytest
os.environ["PROOFFLOW_OFFLINE"] = "1"
from fastapi.testclient import TestClient
from app.core import parse, convert, gen, verify
from app.pipeline import run_pipeline
from app.main import app
from app import mapper

XML = (pathlib.Path(__file__).parent.parent / "app" / "sample.xml").read_text()


def fidelity(bugs):
    m = parse(XML)
    out = convert(m, inject_bugs=bugs, mapper=mapper.map_unknown)
    res = [verify(m, out, s) for s in gen(m)]
    return sum(r["ok"] for r in res), len(res)


def test_scenario_count_matches_official_range():
    assert 15 <= len(gen(parse(XML))) <= 20


def test_timeout_scenario_exists():
    assert any(s["kind"] == "timeout" and "3 days" in s["note"] for s in gen(parse(XML)))


def test_clean_conversion_is_equivalent():
    p, t = fidelity(False)
    assert p == t == 20


def test_planted_bugs_are_detected():
    p, t = fidelity(True)
    assert (p, t) == (12, 20)


def test_pipeline_repairs_to_100():
    d = run_pipeline(XML, True)
    assert [s["pct"] for s in d["snapshots"]] == [60, 80, 100]
    assert len(d["report"]["fixes"]) == 2


def test_failure_is_attributed_to_the_right_steps():
    d = run_pipeline(XML, True)
    assert set(d["snapshots"][0]["bad_steps"]) == {"s8", "s12"}


def test_unknown_actions_go_to_manual_review():
    r = run_pipeline(XML, False)["report"]
    assert {x["legacyAction"] for x in r["review"]} == {"NX_LogAudit", "NX_RunVBScript"}


def test_malformed_xml_rejected():
    with pytest.raises(Exception):
        parse("<Workflow><Action")


def test_api_run_record_and_download():
    c = TestClient(app)
    d = c.post("/api/run", json={"xml": XML, "inject_bugs": True, "filename": "leave.xml"}).json()
    run = d["run"]
    assert run["label"] == "Participant-defined demonstration" and len(run["checklist"]) == 8
    assert [i["status"] for i in run["checklist"][:7]] == ["pass"] * 7
    assert c.get(f'/api/runs/{run["id"]}').status_code == 200
    assert c.get("/api/runs/..%2F..%2Fetc").status_code == 404
    assert c.post("/api/run", json={"xml": "<a", "inject_bugs": True}).status_code == 400
