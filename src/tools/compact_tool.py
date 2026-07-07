from src.tools.base_tool import BaseTool


class CompactTool(BaseTool):
    name = "compact"
    description = "Trigger manual conversation compression."
    input_schema = {
          "type": "object",
          "properties": {
              "focus": {
                  "type": "string",
                  "description": "What aspects to preserve in the summary"
              }
          },
          "required": []
    }

    def run(self, **kwargs) -> str:
        """Request compression - actual compression happens in agent loop."""
        self.validate(kwargs)
        # 不执行压缩，只是发出请求信号
        return "Compression requested. Agent loop will handle context compaction."
