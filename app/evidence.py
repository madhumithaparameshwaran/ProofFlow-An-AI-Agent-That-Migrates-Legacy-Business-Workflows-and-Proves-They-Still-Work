"""Labelled run records: input, expected result (official step), actual result and evidence."""
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from .core import flat

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "runs"
MCP_EVIDENCE = ROOT / "evidence" / "mcp_verify_evidence.json"
LABEL = "Participant-defined demonstration"


def read_mcp():
    try:
        return json.loads(MCP_EVIDENCE.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_run(xml, filename, bugs, res):
    now = datetime.now(timezone.utc)
    snaps, rep = res["snapshots"], res["report"]
    first, last = snaps[0], snaps[-1]
    steps = list(flat(res["workflow"]))
    conds = sum(s["type"] == "Condition" for s in steps)
    n = last["total"]
    fails = [r for r in first["rows"] if not r["ok"]]
    series = " → ".join(f'{s["pct"]}%' for s in snaps)
    mcp = read_mcp()

    def item(i, expected, status, actual):
        return {"n": i, "expected": expected, "status": status, "actual": actual}

    if bugs and fails:
        f = fails[0]
        c5 = item(5, "Planted bug caught; exact failing scenario shown", "pass",
                  f'Round 1: {len(fails)} of {n} scenarios failed. First: decision "{f["decision"] or "(empty)"}", '
                  f'days {f["days"]}. Legacy gave "{f["L"]}", converted gave "{f["M"]}" (diverges at step {f["step"]}).')
    elif bugs:
        c5 = item(5, "Planted bug caught; exact failing scenario shown", "fail", "Planted bugs were on but no scenario failed.")
    else:
        c5 = item(5, "Planted bug caught; exact failing scenario shown", "skipped", "Planted bugs were switched off for this run.")
    ok6 = last["pct"] == 100 and (not bugs or len(snaps) > 1)
    review = rep["review"]
    c7 = (item(7, "Unconvertible step flagged for manual review with an explanation", "pass",
               "; ".join(f'{r["legacyAction"]} (step {r["sourceId"]}, confidence {r["confidence"]}, {r.get("rationale") or "no direct mapping"})'
                         for r in review))
          if review else item(7, "Unconvertible step flagged for manual review with an explanation", "skipped",
                              "No unsupported step in this file."))
    if mcp:
        v = mcp.get("verify_clean", {})
        c8 = item(8, "Final proof report shown; an AI assistant calls the verify tool through MCP", "pass",
                  f'Report produced. MCP client call recorded at {mcp.get("timestamp")}: proofflow_verify on the clean conversion '
                  f'gave {v.get("fidelity_pct")}% over {v.get("total")} scenarios; on a planted-bug conversion it gave '
                  f'{mcp.get("verify_planted_bug", {}).get("fidelity_pct")}%.')
    else:
        c8 = item(8, "Final proof report shown; an AI assistant calls the verify tool through MCP", "pending",
                  "Report produced. No MCP call recorded yet: run `python mcp_demo.py`, then run again.")
    checklist = [
        item(1, "Upload the legacy XML file", "pass",
             f'Received {filename or "pasted text"} ({len(xml.encode())} bytes, sha256 {hashlib.sha256(xml.encode()).hexdigest()[:16]}).'),
        item(2, "Parse it and show the workflow as a diagram", "pass",
             f'Parsed {len(steps)} steps ({conds} conditions). The diagram is drawn in the page from this parsed model.'),
        item(3, "Convert to the modern JSON format", "pass",
             f'{len(list(flat(last["output"])))} converted actions in the final JSON (saved in this run file).'),
        item(4, "Generate about 15 to 20 scenarios and run them on both versions", "pass" if 15 <= n <= 20 else "fail",
             f"{n} scenarios generated from the workflow's own conditions and run on both versions."),
        c5,
        item(6, "Repair loop fixes it; fidelity score rises", "pass" if ok6 else "fail",
             f'Fidelity {series} over {rep["rounds"]} round(s). Auto-repaired: {", ".join(rep["fixes"]) or "none needed"}.'
             + ("" if last["pct"] == 100 else f' Still failing at steps: {", ".join(last["bad_steps"])}.')),
        c7, c8]
    diffs = []
    if bugs and first["pct"] != 80:
        diffs.append(f"The official example mentions 80% to 100%. This run went {series}, because the planted bugs fail "
                     f"{len(fails)} of {n} scenarios. The number follows from the scenario mix and was not tuned to match.")
    diffs.append("Results come from ProofFlow's small interpreter for the supported actions, not from the real Nintex or Power Automate engines.")
    diffs.append("Unconvertible steps are excluded from the score, because their side effects cannot be simulated.")
    if mcp:
        diffs.append("The MCP verify call was made by a client script (mcp_demo.py), not by a chat assistant interface.")
    run = {"id": "run_" + now.strftime("%Y%m%d_%H%M%S_%f"), "label": LABEL, "timestamp": now.isoformat(),
           "input": {"filename": filename or None, "bytes": len(xml.encode()), "plant_bugs": bugs},
           "checklist": checklist, "differences": diffs, "mcp": mcp}
    return run


def save(run, result):
    RUNS.mkdir(exist_ok=True)
    (RUNS / f'{run["id"]}.json').write_text(json.dumps({"run": run, "result": result}, indent=2), encoding="utf-8")
