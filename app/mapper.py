"""Unknown-action mapper: RAG over a mapping knowledge base + LLM with schema-constrained output."""
import json, os, re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
KB = json.loads((Path(__file__).parent / "kb.json").read_text(encoding="utf-8"))
BY_ID = {k["id"]: k for k in KB}
THRESHOLD = 0.8
_col = None

SCHEMA = {
    "type": "object",
    "properties": {
        "target_action": {"type": "string"},
        "parameters": {"type": "object"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["target_action", "confidence", "rationale"],
}


def _tokens(s):
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", s.get("name") or s.get("type") or "").lower()
    return [t for t in re.split(r"[^a-z]+", name) if t]


def _kscore(tk, k):
    return len([t for t in tk if t in k["keywords"]]) / (len(tk) or 1)


def _retrieve(s, n=3):
    """RAG step: embed the action and fetch the closest knowledge-base entries from ChromaDB."""
    global _col
    if _col is None:
        import chromadb
        col = chromadb.Client().get_or_create_collection("proofflow_mappings")
        col.add(ids=[k["id"] for k in KB], documents=[k["text"] + " " + " ".join(k["keywords"]) for k in KB])
        _col = col
    q = " ".join(_tokens(s)) + " " + json.dumps({k: v for k, v in s.items() if k not in ("id", "then", "else")})
    ids = _col.query(query_texts=[q], n_results=n)["ids"][0]
    return [BY_ID[i] for i in ids]


def _ask_llm(s, ctx):
    import anthropic
    tool = {"name": "propose_mapping", "description": "Propose the Power Automate equivalent of a legacy action.",
            "input_schema": SCHEMA}
    prompt = ("Map this legacy workflow action to a Power Automate action. Use ONLY the context below. "
              "If nothing fits, give a confidence under 0.5.\n\nLegacy action:\n"
              + json.dumps({k: v for k, v in s.items() if k not in ("then", "else")})
              + "\n\nContext:\n" + "\n".join(f"- {k['target']}: {k['text']}" for k in ctx))
    msg = anthropic.Anthropic().messages.create(
        model=os.getenv("PROOFFLOW_MODEL", "claude-sonnet-5-5"), max_tokens=500, tools=[tool],
        tool_choice={"type": "tool", "name": "propose_mapping"},
        messages=[{"role": "user", "content": prompt}])
    return next(b.input for b in msg.content if b.type == "tool_use")


def mode() -> str:
    if os.getenv("PROOFFLOW_OFFLINE") == "1":
        return "offline: keyword mapper only"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "LLM (Claude API) + ChromaDB RAG"
    return "no API key: RAG retrieval + keyword fallback"


def map_unknown(s: dict) -> dict:
    offline = os.getenv("PROOFFLOW_OFFLINE") == "1"
    tk, ctx, via, d = _tokens(s), [], "keyword", None
    if not offline:
        try:
            ctx, via = _retrieve(s), "rag"
        except Exception:
            ctx = []
    if not ctx:
        ctx = sorted(KB, key=lambda k: -_kscore(tk, k))[:3]
    if not offline and os.getenv("ANTHROPIC_API_KEY"):
        try:
            d, via = _ask_llm(s, ctx), "llm+" + via
        except Exception:
            d = None
    if not d:
        top = max(ctx, key=lambda k: _kscore(tk, k))
        d = {"target_action": top["target"], "confidence": _kscore(tk, top),
             "rationale": "keyword overlap with the knowledge base"}
    conf = round(float(d["confidence"]), 2)
    base = {"sourceId": s["id"], "confidence": conf, "via": via}
    if conf >= THRESHOLD:
        return {"type": "MappedAction", "action": d["target_action"], **base}
    return {"type": "ManualReview", "legacyAction": s.get("name") or s["type"],
            "suggestion": d["target_action"], "rationale": d.get("rationale", ""), **base}
