from fastmcp import FastMCP, Client
import os

# 1. This is the secret token you chose for yourself
# Your remote server will hash this to create your unique user_id
MY_SECRET_TOKEN = os.environ.get("MY_SECRET_TOKEN")
remote_client = Client(
    "https://expenses-tracker-server.fastmcp.app/mcp",
    auth = MY_SECRET_TOKEN
)

# 2. Use SSETransport to include the Authorization header
mcp = FastMCP.as_proxy(
    remote_client,
    name="Utkarsh Server Proxy",
)

if __name__ == "__main__":
    mcp.run()