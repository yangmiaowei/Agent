from src.tools.tool_manager import ToolManager


class ToolView:
    """Filtered tool schemas exposed to the LLM for one resolve round."""

    def __init__(
        self,
        executor_tm: ToolManager,
        visible_names: set[str],
        extra_schemas: list[dict] | None = None,
    ):
        self._executor_tm = executor_tm
        self._visible = visible_names
        self._extra_schemas = extra_schemas or []

    def list_tools(self) -> list[dict]:
        schemas = [
            schema
            for schema in self._executor_tm.list_tools()
            if schema["name"] in self._visible
        ]
        for schema in self._extra_schemas:
            if schema["name"] in self._visible:
                schemas.append(schema)
        return schemas

    def can_call(self, name: str) -> bool:
        return name in self._visible
