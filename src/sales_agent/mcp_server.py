"""MCP server exposing the sales-data tools over stdio.

This is what lets a Claude *subscription* (via headless Claude Code) power the
agent: Claude Code connects to this server and calls the same three tools the
API provider uses. Run directly with: python -m sales_agent.mcp_server
"""

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("sales")


@mcp.tool()
def get_schema() -> str:
    """Get the sales database schema, distinct filter values, and snapshot dates.

    Call this before writing SQL so filters use real column values.
    """
    return tools.get_schema()


@mcp.tool()
def run_sql(query: str) -> str:
    """Execute a single read-only SELECT (or WITH...SELECT) against DuckDB.

    Use deals_current for 'as of now' questions and deals_snapshots (with
    as_of_date) for point-in-time or change questions. Errors are returned as
    text so the query can be corrected and retried.
    """
    return tools.run_sql(query)


@mcp.tool()
def list_sources() -> str:
    """List ingested source files with their as_of dates and row counts."""
    return tools.list_sources()


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
