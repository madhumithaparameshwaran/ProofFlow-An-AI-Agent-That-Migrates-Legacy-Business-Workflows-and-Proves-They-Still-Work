"""Agent loop built with LangGraph: parse -> test -> convert -> verify -> (repair -> convert)*."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from . import mapper
from .core import parse, flat, gen, convert, verify

MAX_ROUNDS = 4


class S(TypedDict, total=False):
    xml: str; bugs: bool; model: dict; scenarios: list; fixed: list; out: list
    results: list; round: int; events: list; snaps: list; fixes: list; nxt: str


def ev(s, agent, text, level="", **kw):
    return s.get("events", []) + [{"agent": agent, "text": text, "level": level, **kw}]


def fmt(r):
    return f'{r["status"]} · {", ".join(r["emails"]) or "no email"}'


def n_parse(s):
    m = parse(s["xml"])
    f = list(flat(m["steps"]))
    c = sum(x["type"] == "Condition" for x in f)
    return {"model": m, "fixed": [], "fixes": [], "snaps": [], "round": 0,
            "events": ev(s, "Parser Agent", f'Read "{m["name"]}": {len(f)} steps, {c} conditions.')}


def n_test(s):
    sc = gen(s["model"])
    return {"scenarios": sc, "events": ev(s, "Tester Agent",
            f"Generated {len(sc)} scenarios from the workflow logic: normal, boundary, timeout, empty-input and case-variant inputs.")}


def n_convert(s):
    out = convert(s["model"], set(s["fixed"]), s["bugs"], mapper.map_unknown)
    r = s["round"] + 1
    via = sorted({x["via"] for x in flat(out) if "via" in x})
    txt = ("First-pass conversion done" if r == 1 else f"Round {r}: re-converted with the corrected rule")
    txt += f". Unknown actions mapped via: {', '.join(via)}." if via else "."
    return {"out": out, "round": r, "events": ev(s, "Converter Agent", txt)}


def n_verify(s):
    res = [verify(s["model"], s["out"], sc) for sc in s["scenarios"]]
    p, t = sum(r["ok"] for r in res), len(res)
    pct = round(100 * p / t)
    rows = [{"kind": sc["kind"], "note": sc.get("note", ""), "decision": sc["in"]["decision"],
             "days": sc["in"]["days"], "L": fmt(r["L"]), "M": fmt(r["M"]), "ok": r["ok"], "step": r["id"],
             "trace_L": r["L"]["trace"], "trace_M": r["M"]["trace"]} for sc, r in zip(s["scenarios"], res)]
    snaps = s["snaps"] + [{"round": s["round"], "pct": pct, "passed": p, "total": t,
                           "bad_steps": sorted({r["id"] for r in res if r["id"]}), "output": s["out"], "rows": rows}]
    nxt = "end" if p == t or s["round"] >= MAX_ROUNDS else "repair"
    return {"results": res, "snaps": snaps, "nxt": nxt, "events": ev(
        s, "Verifier", f"Round {s['round']}: {p}/{t} scenarios match. Fidelity {pct}%.",
        "ok" if p == t else "bad", snap=len(snaps) - 1, pct=pct, round=s["round"])}


def n_repair(s):
    cnt = {}
    for r in s["results"]:
        if not r["ok"] and r["id"] and r["id"] not in s["fixed"]:
            cnt[r["id"]] = cnt.get(r["id"], 0) + 1
    if not cnt:
        return {"nxt": "end", "events": ev(s, "Repair Agent",
                "Cannot attribute the remaining failures to a single step. Flagging for review.", "bad")}
    sid, n = max(cnt.items(), key=lambda kv: kv[1])
    i = next(i for i, r in enumerate(s["results"]) if r["id"] == sid)
    r = s["results"][i]
    txt = (f'Step {sid} causes {n} failures. Example scenario #{i + 1}: legacy gave "{fmt(r["L"])}", '
           f'converted gave "{fmt(r["M"])}". Re-applying the verified rule to {sid}.')
    return {"nxt": "convert", "fixed": s["fixed"] + [sid],
            "fixes": s["fixes"] + [f"{sid} ({n} failing scenarios)"], "events": ev(s, "Repair Agent", txt)}


g = StateGraph(S)
for name, fn in [("parse", n_parse), ("test", n_test), ("convert", n_convert), ("verify", n_verify), ("repair", n_repair)]:
    g.add_node(name, fn)
g.add_edge(START, "parse"); g.add_edge("parse", "test"); g.add_edge("test", "convert"); g.add_edge("convert", "verify")
g.add_conditional_edges("verify", lambda s: s["nxt"], {"repair": "repair", "end": END})
g.add_conditional_edges("repair", lambda s: s["nxt"], {"convert": "convert", "end": END})
APP = g.compile()


def run_pipeline(xml: str, inject_bugs: bool = True) -> dict:
    s = APP.invoke({"xml": xml, "bugs": inject_bugs, "events": []})
    last = s["snaps"][-1]
    review = [x for x in flat(s["out"]) if x["type"] == "ManualReview"]
    if review:
        s["events"] = s["events"] + [{"agent": "Review Agent", "level": "",
            "text": f"{len(review)} step(s) below the {mapper.THRESHOLD} confidence threshold were flagged for manual review."}]
    return {"name": s["model"]["name"], "workflow": s["model"]["steps"], "events": s["events"], "snapshots": s["snaps"],
            "report": {"fidelity": last["pct"], "passed": last["passed"], "total": last["total"],
                       "rounds": s["round"], "fixes": s["fixes"], "review": review,
                       "threshold": mapper.THRESHOLD}}
