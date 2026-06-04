#!/usr/bin/env python3
"""
Task Manager MCP Server

An MCP server that provides task management capabilities to Claude,
including creating, listing, updating, and deleting tasks, with
priority levels and status tracking.
"""

import json
import os
from datetime import datetime
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ─── Data Store ───────────────────────────────────────────────────────────────

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(DATA_DIR, "tasks.json")


def _load_tasks() -> list[dict]:
    """Load tasks from the JSON data file."""
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def _save_tasks(tasks: list[dict]) -> None:
    """Persist tasks to the JSON data file."""
    with open(DATA_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def _next_id(tasks: list[dict]) -> int:
    """Get the next available task ID."""
    if not tasks:
        return 1
    return max(t["id"] for t in tasks) + 1


# ─── Tool Definitions ────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    types.Tool(
        name="create_task",
        description="Create a new task with a title, optional description, priority, and due date.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title of the task"},
                "description": {"type": "string", "description": "Detailed description of the task", "default": ""},
                "priority": {
                    "type": "string",
                    "description": "Priority level",
                    "enum": ["low", "medium", "high", "urgent"],
                    "default": "medium",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format (optional)",
                },
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="list_tasks",
        description="List all tasks, optionally filtered by status and/or priority.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "description": "Filter by priority",
                    "enum": ["low", "medium", "high", "urgent"],
                },
            },
        },
    ),
    types.Tool(
        name="get_task",
        description="Get full details of a specific task by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to retrieve"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="update_task",
        description="Update an existing task by ID. Only provided fields will be changed.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to update"},
                "title": {"type": "string", "description": "New title for the task"},
                "description": {"type": "string", "description": "New description"},
                "priority": {
                    "type": "string",
                    "description": "New priority",
                    "enum": ["low", "medium", "high", "urgent"],
                },
                "status": {
                    "type": "string",
                    "description": "New status",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                },
                "due_date": {
                    "type": "string",
                    "description": "New due date in YYYY-MM-DD format, or empty string to clear",
                },
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="delete_task",
        description="Delete a task by its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to delete"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="get_task_stats",
        description="Get summary statistics about all tasks, including status/priority breakdowns and overdue alerts.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]

# ─── Tool Handlers ────────────────────────────────────────────────────────────


def _handle_create_task(args: dict) -> list[types.TextContent]:
    title = args.get("title", "")
    description = args.get("description", "")
    priority = args.get("priority", "medium")
    due_date = args.get("due_date")

    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            return [types.TextContent(type="text", text="Error: Invalid due_date format. Use YYYY-MM-DD.")]

    tasks = _load_tasks()
    task = {
        "id": _next_id(tasks),
        "title": title,
        "description": description,
        "priority": priority,
        "status": "pending",
        "due_date": due_date or None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    tasks.append(task)
    _save_tasks(tasks)

    msg = f"✅ Task #{task['id']} created: '{title}' [{priority}]"
    if due_date:
        msg += f" (due {due_date})"
    return [types.TextContent(type="text", text=msg)]


def _handle_list_tasks(args: dict) -> list[types.TextContent]:
    status = args.get("status")
    priority = args.get("priority")
    tasks = _load_tasks()

    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if priority:
        tasks = [t for t in tasks if t["priority"] == priority]

    if not tasks:
        return [types.TextContent(type="text", text="No tasks found.")]

    lines = [f"📋 Found {len(tasks)} task(s):\n"]
    for t in tasks:
        due = f" | Due: {t['due_date']}" if t.get("due_date") else ""
        lines.append(f"  #{t['id']} [{t['status']}] [{t['priority']}] {t['title']}{due}")
        if t.get("description"):
            lines.append(f"      {t['description']}")

    return [types.TextContent(type="text", text="\n".join(lines))]


def _handle_get_task(args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)

    if not task:
        return [types.TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    lines = [
        f"📝 Task #{task['id']}",
        f"   Title:       {task['title']}",
        f"   Description: {task.get('description') or '(none)'}",
        f"   Priority:    {task['priority']}",
        f"   Status:      {task['status']}",
        f"   Due Date:    {task.get('due_date') or '(none)'}",
        f"   Created:     {task['created_at']}",
        f"   Updated:     {task['updated_at']}",
    ]
    return [types.TextContent(type="text", text="\n".join(lines))]


def _handle_update_task(args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)

    if not task:
        return [types.TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    if "title" in args and args["title"] is not None:
        task["title"] = args["title"]
    if "description" in args and args["description"] is not None:
        task["description"] = args["description"]
    if "priority" in args and args["priority"] is not None:
        task["priority"] = args["priority"]
    if "status" in args and args["status"] is not None:
        task["status"] = args["status"]
    if "due_date" in args:
        dd = args["due_date"]
        if dd == "":
            task["due_date"] = None
        elif dd is not None:
            try:
                datetime.strptime(dd, "%Y-%m-%d")
                task["due_date"] = dd
            except ValueError:
                return [types.TextContent(type="text", text="Error: Invalid due_date format. Use YYYY-MM-DD.")]

    task["updated_at"] = datetime.now().isoformat()
    _save_tasks(tasks)

    return [types.TextContent(type="text", text=f"✅ Task #{task_id} updated: '{task['title']}' [{task['status']}] [{task['priority']}]")]


def _handle_delete_task(args: dict) -> list[types.TextContent]:
    task_id = args.get("task_id")
    tasks = _load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)

    if not task:
        return [types.TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    tasks = [t for t in tasks if t["id"] != task_id]
    _save_tasks(tasks)

    return [types.TextContent(type="text", text=f"🗑️ Task #{task_id} deleted: '{task['title']}'")]


def _handle_get_task_stats(args: dict) -> list[types.TextContent]:
    tasks = _load_tasks()

    if not tasks:
        return [types.TextContent(type="text", text="No tasks in the system.")]

    total = len(tasks)
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}

    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
        by_priority[t["priority"]] = by_priority.get(t["priority"], 0) + 1

    lines = [f"📊 Task Statistics ({total} total)\n"]
    lines.append("  By Status:")
    for s in ["pending", "in_progress", "done", "cancelled"]:
        count = by_status.get(s, 0)
        bar = "█" * count
        lines.append(f"    {s:15s} {count} {bar}")

    lines.append("\n  By Priority:")
    for p in ["urgent", "high", "medium", "low"]:
        count = by_priority.get(p, 0)
        bar = "█" * count
        lines.append(f"    {p:15s} {count} {bar}")

    # Overdue check
    now_str = datetime.now().strftime("%Y-%m-%d")
    overdue = [
        t for t in tasks
        if t.get("due_date") and t["due_date"] < now_str and t["status"] not in ("done", "cancelled")
    ]
    if overdue:
        lines.append(f"\n  ⚠️  {len(overdue)} overdue task(s)!")

    return [types.TextContent(type="text", text="\n".join(lines))]


# Map tool names to handler functions
TOOL_HANDLERS = {
    "create_task": _handle_create_task,
    "list_tasks": _handle_list_tasks,
    "get_task": _handle_get_task,
    "update_task": _handle_update_task,
    "delete_task": _handle_delete_task,
    "get_task_stats": _handle_get_task_stats,
}

# ─── Server Setup ─────────────────────────────────────────────────────────────

server = Server("task-manager")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return the list of available tools."""
    return TOOL_DEFINITIONS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch tool calls to the appropriate handler."""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return [types.TextContent(type="text", text=f"Error: Unknown tool '{name}'.")]
    return handler(arguments)


# ─── Entry Point ──────────────────────────────────────────────────────────────


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
