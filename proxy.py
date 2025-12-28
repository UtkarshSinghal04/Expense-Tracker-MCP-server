from fastmcp import FastMCP
from fastmcp.client.transports import SSETransport
import os

# 1. This is the secret token you chose for yourself
# Your remote server will hash this to create your unique user_id
MY_SECRET_TOKEN = os.environ.get("MY_SECRET_TOKEN")

# 2. Use SSETransport to include the Authorization header
mcp = FastMCP.as_proxy(
    SSETransport(
        "https://expenses-tracker-server.fastmcp.app/mcp",
        headers={"Authorization": f"Bearer {MY_SECRET_TOKEN}"}
    ),
    name="Utkarsh Server Proxy"
)

if __name__ == "__main__":
    mcp.run()