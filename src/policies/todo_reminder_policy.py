from src.policies.base_policy import BasePolicy
from src.context.policy_context import PolicyContext


class TodoReminderPolicy(BasePolicy):

    def after_tool(self, context: PolicyContext):
        use_todo = any(
            b.name == "todo"
            for b in context.tool_blocks
            if b.type == "tool_use"
        )

        if use_todo:
            context.state["rounds_since_todo"] = 0
        else:
            context.state["rounds_since_todo"] = (
                context.state.get("rounds_since_todo", 0) + 1
            )

        results = list(context.tool_results)
        if context.state["rounds_since_todo"] >= 3:
            results.append({
                "type": "text",
                "text": "<reminder>Update your todos.</reminder>",
            })
        return results
