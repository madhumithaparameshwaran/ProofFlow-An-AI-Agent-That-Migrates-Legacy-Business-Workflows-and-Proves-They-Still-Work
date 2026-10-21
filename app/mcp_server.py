"""MCP server exposing ProofFlow as tools. Run: python -m app.mcp_server (stdio)."""
try:  # mcp >= 2 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from . import mapper
from .core import parse, convert, gen, verify

mcp = FastMCP("proofflow")


@mcp.tool()
def proofflow_convert(xml: str) -> dict:
    """Convert a legacy workflow XML export into the modern JSON flow format."""
    m = parse(xml)
    return {"name": m["name"], "actions": convert(m, mapper=mapper.map_unknown)}


@mcp.tool()
def proofflow_test(xml: str) -> dict:
    """Generate test scenarios (normal, boundary, timeout, edge, adversarial) from the workflow logic."""
    sc = gen(parse(xml))
    return {"count": len(sc), "scenarios": sc}


@mcp.tool()
def proofflow_verify(xml: str, converted_actions: list) -> dict:
    """Run every scenario on the legacy and converted workflow; return fidelity and failures."""
    m = parse(xml)
    sc = gen(m)
    res = [verify(m, converted_actions, s) for s in sc]
    bad = [{"scenario": s["in"], "legacy": r["L"], "converted": r["M"], "step": r["id"]}
           for s, r in zip(sc, res) if not r["ok"]]
    return {"fidelity_pct": round(100 * (len(res) - len(bad)) / len(res)), "total": len(res), "failures": bad}


if __name__ == "__main__":
    mcp.run()
