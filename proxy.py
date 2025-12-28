from fastmcp import FastMCP

# Create a proxy to your remote FastMCP Cloud server
mcp = FastMCP.as_proxy(
    "https://expenses-tracker-server.fastmcp.app/mcp",  # Standard FastMCP Cloud URL
    name="Utkarsh Server Proxy"
)

if __name__ == "__main__":
    mcp.run()