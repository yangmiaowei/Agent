from src.context.policy_context import PolicyContext


class BasePolicy:
    def before_model(self, context: PolicyContext):
        return context.messages

    def after_model(self, context: PolicyContext):
        return context.tool_blocks

    def before_tool(self, context: PolicyContext):
        return context.tool_blocks

    def after_tool(self, context: PolicyContext):
        return context.tool_results

    def before_next_round(self, context: PolicyContext):
        pass
