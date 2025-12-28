import os
import json
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# --- Auth Logic: Token to UserID ---

def generate_user_id(auth_header: str) -> str:
    """Creates a stable, unique User ID by hashing the secret token."""
    return hashlib.sha256(auth_header.encode()).hexdigest()[:16]

class AuthMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers()
        auth_header = headers.get("authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            raise ToolError("Unauthorized: Please provide a Bearer Token in your config.")

        # Generate a unique ID based on their specific token
        user_id = generate_user_id(auth_header)
        
        # Save it in the context state for the tools to use
        context.fastmcp_context.set_state("user_id", user_id)
        
        return await call_next(context)

# --- Initialize Server and Supabase ---

# Initialize FastMCP with the Auth Middleware
mcp = FastMCP("Expense-Tracker Server", middleware=[AuthMiddleware()])
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- Helper Function (Internal) ---

async def get_budget_status(user_id: str, new_expense: float) -> str:
    """Checks budget against current month's spending."""
    # Fetch budget
    res = supabase.table("settings").select("total_budget").eq("user_id", user_id).execute()
    if not res.data:
        return ""
    
    budget = res.data[0]['total_budget']
    
    # Fetch monthly spend
    start_of_month = datetime.now().strftime('%Y-%m-01')
    spend_res = supabase.table("transactions") \
        .select("amount") \
        .eq("user_id", user_id) \
        .eq("type", "expense") \
        .gte("date", start_of_month) \
        .execute()
    
    spent = sum(item['amount'] for item in spend_res.data)
    remaining = budget - spent - new_expense
    
    if 0 <= remaining <= 500:
        return f"Warning: {remaining:.2f} left in your monthly budget."
    elif remaining < 0:
        return f"Budget Exceeded by {abs(remaining):.2f}!"
    return ""

# --- MCP Tools ---
@mcp.tool()
async def ping(ctx: Context) -> str:
    user_id = ctx.get_state("user_id")
    return f"pong for {user_id}"

@mcp.tool()
async def add_transaction(
    ctx: Context,
    amount: float, 
    category: str, 
    subcategory: str = "", 
    note: str = "", 
    date: str = None, 
    is_credit: bool = False
) -> str:
    """Add a new transaction. (Auth handled automatically)"""
    user_id = ctx.get_state("user_id")

    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    
    t_type = 'credit' if is_credit else 'expense'
    
    data = {
        "user_id": user_id,
        "amount": amount,
        "type": t_type,
        "category": category,
        "subcategory": subcategory,
        "note": note,
        "date": date
    }
    
    supabase.table("transactions").insert(data).execute()
    
    msg = f"Logged {t_type}: {amount}."
    if not is_credit:
        budget_msg = await get_budget_status(user_id, amount)
        if budget_msg: msg += f"\n{budget_msg}"
        
    return msg

@mcp.tool()
async def list_expenses(
    ctx: Context,
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None, 
    category: Optional[str] = None,
    limit: int = 50
) -> Any:
    """List transactions with optional filters for the authenticated user."""
    user_id = ctx.get_state("user_id")

    query = supabase.table("transactions").select("*").eq("user_id", user_id)
    
    if start_date:
        query = query.gte("date", start_date)
    if end_date:
        query = query.lte("date", end_date)
    if category:
        query = query.eq("category", category)
        
    res = query.order("date", desc=True).limit(limit).execute()
    
    return res.data if res.data else "No transactions found."

@mcp.tool()
async def get_summary(
    ctx: Context,
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> Dict[str, float]:
    """Get total spending and credits for the authenticated user within a period."""
    user_id = ctx.get_state("user_id")

    query = supabase.table("transactions").select("type, amount").eq("user_id", user_id)
    
    if start_date:
        query = query.gte("date", start_date)
    if end_date:
        query = query.lte("date", end_date)
        
    res = query.execute()
    
    expenses = 0.0
    credits = 0.0
    
    for row in res.data:
        amount = float(row.get("amount", 0))
        if row.get("type") == "expense":
            expenses += amount
        elif row.get("type") == "credit":
            credits += amount
            
    return {
        "Total Expense": expenses,
        "Total Credit": credits,
        "Net Balance": credits - expenses
    }

@mcp.tool()
async def search_transactions(
    ctx: Context,
    date: str, 
    amount: float, 
    category: str
) -> str:
    """
    Search for transactions for the authenticated user to get their IDs. 
    Use this before updating or deleting to find the correct record.
    """
    user_id = ctx.get_state("user_id")

    # Query Supabase with user_id filter for security
    res = supabase.table("transactions") \
        .select("id, date, amount, category, subcategory, note") \
        .eq("user_id", user_id) \
        .eq("date", date) \
        .eq("amount", amount) \
        .eq("category", category) \
        .execute()
    
    if not res.data:
        return "No matching transactions found."
    
    results = []
    for row in res.data:
        results.append(
            f"ID: {row['id']} | {row['date']} | {row['amount']} | "
            f"{row['category']} ({row.get('subcategory', '')}) | Note: {row.get('note', '')}"
        )
    
    return "\n".join(results)

@mcp.tool()
async def update_transaction_by_id(
    ctx: Context,
    t_id: int, 
    new_amount: Optional[float] = None
) -> str:
    """Update a specific transaction using the ID found from search. (Auth handled automatically)"""
    user_id = ctx.get_state("user_id")

    if new_amount is None:
        return "Nothing to update."

    # Update call with double filter (id AND user_id)
    res = supabase.table("transactions") \
        .update({"amount": new_amount}) \
        .eq("id", t_id) \
        .eq("user_id", user_id) \
        .execute()
    
    if res.data:
        return f"Transaction {t_id} successfully updated to {new_amount}."
    return "Transaction not found or unauthorized."

@mcp.tool()
async def delete_transaction_by_id(ctx: Context, t_id: int) -> str:
    """Delete a specific transaction using the ID found from search. (Auth handled automatically)"""
    user_id = ctx.get_state("user_id")

    # Delete call with double filter (id AND user_id)
    res = supabase.table("transactions") \
        .delete() \
        .eq("id", t_id) \
        .eq("user_id", user_id) \
        .execute()
    
    # Supabase returns the deleted row in res.data if successful
    if res.data:
        return f"Transaction {t_id} successfully deleted."
    return "Transaction not found or unauthorized."

@mcp.tool()
async def set_budget(ctx: Context, amount: float) -> str:
    """Set or update the monthly budget for the authenticated user."""
    user_id = ctx.get_state("user_id")

    data = {"user_id": user_id, "total_budget": amount}
    supabase.table("settings").upsert(data).execute()
    return f"Budget updated to {amount}."

@mcp.resource("config://categories", mime_type="application/json")
async def get_categories() -> str:
    """Fetches categories and subcategories directly from Supabase."""
    try:
        default_categories = {
            "categories": [
                "Food & Dining", "Transportation", "Shopping", "Entertainment",
                "Bills & Utilities", "Healthcare", "Travel", "Education",
                "Business", "Other"
            ]
        }
        try:
            res = supabase.table("categories").select("*").execute()
            category_dict = {item['name']: item['subcategories'] for item in res.data}
            return json.dumps(category_dict)
        except FileNotFoundError:
            return json.dumps(default_categories, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch categories: {str(e)}"})

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=3001)