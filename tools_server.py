from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Tools")


@mcp.tool()
async def add(a: int, b: int) -> int:
    """add a and b"""
    return a + b


@mcp.tool()
async def multiply(a: int, b: int) -> int:
    """multiply a and b"""
    return a * b


if __name__ == "__main__":
    mcp.run(transport="stdio")
