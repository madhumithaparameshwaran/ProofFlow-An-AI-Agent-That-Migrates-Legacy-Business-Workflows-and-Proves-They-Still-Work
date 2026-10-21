"""Calls the ProofFlow MCP server the way an assistant would, and saves evidence.
Run from the project root:  python mcp_demo.py [path/to/workflow.xml]"""
import asyncio, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.core import parse, convert

ROOT = Path(__file__).parent


def unwrap(res):
    sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)  # name differs by SDK version
    if sc is not None:
        return sc
    return json.loads(res.content[0].text)


async def main(path):
    xml = Path(path).read_text(encoding="utf-8")
    params = StdioServerParameters(command=sys.python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .envexecutable, args=["-m", "app.mcp_server"],
                                   cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("Tools offered by the server:", tools)
            scenarios = unwrap(await s.call_tool("proofflow_test", {"xml": xml}))["scenarios"]
            print(f"proofflow_test -> {len(scenarios)} scenarios")
            conv = unwrap(await s.call_tool("proofflow_convert", {"xml": xml}))
            clean = unwrap(await s.call_tool("proofflow_verify", {"xml": xml, "converted_actions": conv["actions"]}))
            print(f"proofflow_verify (clean conversion) -> {clean['fidelity_pct']}% of {clean['total']}")
            buggy = convert(parse(xml), inject_bugs=True)
            bad = unwrap(await s.call_tool("proofflow_verify", {"xml": xml, "converted_actions": buggy}))
            print(f"proofflow_verify (planted bugs) -> {bad['fidelity_pct']}%, {len(bad['failures'])} failing scenarios")
    ev = {"timestamp": datetime.now(timezone.utc).isoformat(), "client": "mcp_demo.py (MCP stdio client)",
          "server_command": "python -m app.mcp_server", "tools_listed": tools, "scenarios_generated": len(scenarios),
          "verify_clean": {"fidelity_pct": clean["fidelity_pct"], "total": clean["total"]},
          "verify_planted_bug": {"fidelity_pct": bad["fidelity_pct"], "total": bad["total"],
                                 "first_failure": bad["failures"][0] if bad["failures"] else None}}
    out = ROOT / "evidence" / "mcp_verify_evidence.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    print("Evidence saved to", out)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "app" / "sample.xml")))
