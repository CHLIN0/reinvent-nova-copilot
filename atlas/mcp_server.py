"""stdio MCP server exposing the re:Invent Nova Copilot tools to any MCP client.

The tools are the same ones the Nova Pro agent uses (atlas.tools): catalog
search and lookup, venue routing, itinerary check and planning, and the
attendee's schedule and favorites. They complement the official re:Invent
MCP server, which can be registered next to this one:

    {
      "mcpServers": {
        "reinvent-official": {
          "type": "http",
          "url": "https://api.awsevents.com/mcp"
        },
        "reinvent-nova-copilot": {
          "command": "python3",
          "args": ["-m", "atlas.mcp_server"],
          "env": {"PYTHONPATH": "/path/to/reinvent-nova-copilot"}
        }
      }
    }

Run: python3 -m atlas.mcp_server   (from the repo root)

add_favorites writes to the attendee's real AWS Events schedule. It is
annotated as non-read-only so MCP clients ask the user first, and it also
refuses to run unless the caller passes confirm=true. Both are advisory: the
calling model supplies confirm, so the human gate is the MCP client's own
tool-approval prompt. The CLI agent (chat.py) enforces confirmation itself.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from atlas.tools import TOOL_SPECS, dispatch

mcp = FastMCP("reinvent-nova-copilot")
_DESC = {s["name"]: s["description"] for s in TOOL_SPECS}
_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _run(name: str, args: dict) -> dict:
    result, ok = dispatch(name, {k: v for k, v in args.items() if v is not None})
    if not ok:
        raise ValueError(result.get("error", "tool failed"))  # FastMCP returns it with isError=true
    return result


@mcp.tool(description=_DESC["search_sessions"], annotations=_READ)
def search_sessions(
    query: str = "",
    types: list[str] | None = None,
    levels: list[str] | None = None,
    topics: list[str] | None = None,
    day: str | None = None,
    venue: str | None = None,
    limit: int = 10,
) -> dict:
    return _run("search_sessions", dict(query=query, types=types, levels=levels, topics=topics, day=day, venue=venue, limit=limit))


@mcp.tool(description=_DESC["get_session"], annotations=_READ)
def get_session(session_id: str) -> dict:
    return _run("get_session", {"session_id": session_id})


@mcp.tool(description=_DESC["route_between"], annotations=_READ)
def route_between(from_venue: str, to_venue: str, depart_at: str | None = None, prefer: str = "fastest") -> dict:
    return _run("route_between", dict(from_venue=from_venue, to_venue=to_venue, depart_at=depart_at, prefer=prefer))


@mcp.tool(description=_DESC["check_itinerary"], annotations=_READ)
def check_itinerary(session_ids: list[str], buffer_min: int = 10) -> dict:
    return _run("check_itinerary", dict(session_ids=session_ids, buffer_min=buffer_min))


@mcp.tool(description=_DESC["plan_itinerary"], annotations=_READ)
def plan_itinerary(
    candidate_ids: list[str] | None = None,
    query: str | None = None,
    must: list[str] | None = None,
    day: str | None = None,
    prefer: str = "fastest",
    buffer_min: int = 10,
    max_sessions: int = 6,
) -> dict:
    return _run(
        "plan_itinerary",
        dict(candidate_ids=candidate_ids, query=query, must=must, day=day, prefer=prefer, buffer_min=buffer_min, max_sessions=max_sessions),
    )


@mcp.tool(description=_DESC["get_my_schedule"], annotations=_READ)
def get_my_schedule() -> dict:
    return _run("get_my_schedule", {})


@mcp.tool(
    description=_DESC["add_favorites"] + " Pass confirm=true only after the user explicitly approved these exact sessions.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True),
)
def add_favorites(session_ids: list[str], confirm: bool = False) -> dict:
    if not confirm:
        raise ValueError(f"Not saved: add_favorites needs confirm=true after the user approves these sessions: {session_ids}")
    return _run("add_favorites", {"session_ids": session_ids})


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
