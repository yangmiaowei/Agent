# Task Manager MCP Server

An MCP (Model Context Protocol) server that gives Claude task management capabilities.

## Features

### 🛠️ Tools (6 tools)

| Tool | Description |
|------|-------------|
| `create_task` | Create a new task with title, description, priority, and due date |
| `list_tasks` | List tasks, optionally filtered by status and/or priority |
| `get_task` | Get full details of a specific task |
| `update_task` | Update task fields (title, description, priority, status, due date) |
| `delete_task` | Delete a task by ID |
| `get_task_stats` | Get summary statistics with status/priority breakdowns & overdue alerts |

### 📚 Resources (2 resources)

| Resource URI | Description |
|--------------|-------------|
| `taskmanager://tasks` | All tasks as JSON |
| `taskmanager://stats` | Task statistics summary as JSON |

### 📋 Task Properties

- **title** (required) — Short task title
- **description** (optional) — Detailed description
- **priority** — `low` · `medium` · `high` · `urgent`
- **status** — `pending` · `in_progress` · `done` · `cancelled`
- **due_date** (optional) — In `YYYY-MM-DD` format

## Installation

```bash
cd task-manager-mcp
python3 -m venv venv
source venv/bin/activate
pip install mcp
```

## Running

### Direct execution
```bash
python3 server.py
```

### With MCP Inspector (for testing)
```bash
npx @anthropics/mcp-inspector python3 server.py
```

## Registering with Claude

Add the contents of `mcp.json` to your `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "task-manager": {
      "command": "/path/to/venv/bin/python3",
      "args": ["/path/to/server.py"]
    }
  }
}
```

## Data Storage

Tasks are persisted in `tasks.json` in the same directory as `server.py`.

## Example Usage (via Claude)

Once registered, you can ask Claude to:
- "Create a high-priority task called 'Review PR' due Friday"
- "Show me all pending tasks"
- "Mark task #3 as done"
- "Give me task statistics"
- "Delete task #2"
