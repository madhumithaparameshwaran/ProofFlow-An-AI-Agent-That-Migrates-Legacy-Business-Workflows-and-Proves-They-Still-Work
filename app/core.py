"""Parser, converter, simulator, test generator and verifier."""
from lxml import etree


def parse(xml: str) -> dict:
    root = etree.fromstring(xml.strip().encode("utf-8"))
    parents: dict = {}

    def node(el, parent):
        o = dict(el.attrib)
        parents[o.get("id")] = parent
        for c in el:
            if c.tag in ("Then", "Else"):
                o[c.tag.lower()] = [node(a, o.get("id")) for a in c if a.tag == "Action"]
        return o

    steps = [node(a, None) for a in root if a.tag == "Action"]
    return {"name": root.get("name", "Workflow"), "steps": steps, "parents": parents}


def flat(steps):
    for s in steps or []:
        yield s
        yield from flat(s.get("then"))
        yield from flat(s.get("else"))


def convert(model, fixed=frozenset(), inject_bugs=False, mapper=None):
    """Rule-based conversion. Unknown actions go to `mapper` (RAG + LLM).
    inject_bugs plants two known mistakes (s12 boundary operator, s8 email recipient) for the demo; `fixed` lists steps already repaired."""

    def c(s):
        bug = inject_bugs and s["id"] not in fixed
        t = s["type"]
        if t == "SetVariable":
            return {"type": t, "sourceId": s["id"], "name": s["name"], "value": s["value"]}
        if t == "RequestApproval":
            return {"type": "Approval", "sourceId": s["id"], "assignee": s.get("assignee"),
                    "timeoutDays": int(s.get("timeoutDays", 0)), "outputVar": s["outcomeVar"]}
        if t == "SendEmail":
            to = "HR" if bug and s["id"] == "s8" else s["to"]  # planted bug: rejection email misrouted
            return {"type": t, "sourceId": s["id"], "to": to, "subject": s.get("subject", "")}
        if t == "Condition":
            op = "greaterOrEquals" if bug and s["id"] == "s12" else s["op"]
            o = {"type": "If", "sourceId": s["id"],
                 "expression": {"left": s["var"], "op": op, "right": s["value"]},
                 "then": [c(x) for x in s.get("then", [])]}
            if s.get("else"):
                o["else"] = [c(x) for x in s["else"]]
            return o
        if mapper:
            return mapper(s)
        return {"type": "ManualReview", "sourceId": s["id"], "legacyAction": s.get("name") or t,
                "suggestion": "none", "confidence": 0.0, "via": "none"}

    return [c(s) for s in model["steps"]]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cmp(a, op, b):
    x, y = _num(a), _num(b)
    n = x is not None and y is not None
    if op == "equals":
        return str(a) == str(b)
    if op == "notEquals":
        return str(a) != str(b)
    if op == "greater":
        return n and x > y
    if op == "greaterOrEquals":
        return n and x >= y
    if op == "less":
        return n and x < y
    return False


def run(steps, inp):
    """One interpreter for both schemas (legacy XML model and converted JSON)."""
    v, em, tr = dict(inp), [], []

    def go(lst):
        for s in lst or []:
            t, sid = s["type"], s.get("id") or s.get("sourceId")
            if t == "SetVariable":
                v[s["name"]] = s["value"]
            elif t in ("RequestApproval", "Approval"):
                v[s.get("outcomeVar") or s.get("outputVar")] = inp.get("decision") or "NoReply"
            elif t == "SendEmail":
                em.append(s["to"])
                tr.append(f"{sid}:{s['to']}")
            elif t in ("Condition", "If"):
                e = s.get("expression") or {"left": s["var"], "op": s["op"], "right": s["value"]}
                r = cmp(v.get(e["left"]), e["op"], e["right"])
                tr.append(sid + ("T" if r else "F"))
                go(s.get("then") if r else s.get("else"))

    go(steps)
    return {"status": v.get("status", "none"), "emails": em, "trace": tr}


def gen(model):
    """Tester: derive 20 scenarios from the conditions and approval timeout found in the workflow."""
    eq, nu = [], []
    for s in flat(model["steps"]):
        if s["type"] == "Condition":
            if s["var"] == "decision" and s["value"] not in eq:
                eq.append(s["value"])
            if s["var"] == "days" and _num(s["value"]) is not None:
                nu.append(int(_num(s["value"])))
    t = nu[0] if nu else 5
    timeout = next((s.get("timeoutDays", "0") for s in flat(model["steps"]) if s["type"] == "RequestApproval"), "0")
    up = (eq[0] if eq else "Approved").upper()
    decisions = list(dict.fromkeys(eq + ["NoReply", "", up]))
    days = list(dict.fromkeys([t - 1, t, t + 1, 30]))
    out = []
    for d in decisions:
        for n in days:
            kind = ("adversarial" if d == up else "timeout" if d == "NoReply" else "edge" if d == ""
                    else "boundary" if abs(n - t) <= 1 else "normal")
            note = f"no reply for {timeout} days, request escalates" if kind == "timeout" else ""
            out.append({"in": {"decision": d, "days": str(n)}, "kind": kind, "note": note})
    return out


def _base(e):
    return e.split(":")[0] if ":" in e else (e[:-1] if e[-1] in "TF" else e)


def verify(model, converted, sc):
    """Run one scenario on both versions; on mismatch, find the first diverging step."""
    L, M = run(model["steps"], sc["in"]), run(converted, sc["in"])
    ok = (L["status"], L["emails"]) == (M["status"], M["emails"])
    sid = None
    if not ok:
        for i in range(max(len(L["trace"]), len(M["trace"]))):
            a = L["trace"][i] if i < len(L["trace"]) else None
            b = M["trace"][i] if i < len(M["trace"]) else None
            if a != b:
                if a and b and _base(a) == _base(b):
                    sid = _base(a)                      # same step, different result
                else:
                    e = a or b                          # a branch was taken or skipped wrongly
                    sid = _base(e) if ":" not in e else model["parents"].get(_base(e), _base(e))
                break
    return {"L": L, "M": M, "ok": ok, "id": sid}
