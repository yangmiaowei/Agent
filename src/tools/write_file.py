from src.tools.base_tool import BaseTool, safe_path
from src.tools.tool_manager import tool

@tool
class WriteFile(BaseTool):
    name = "write_file"
    description = "Write content to file."
    input_schema = {
        "type": "object", 
        "properties": {
            "path": {"type": "string"}, 
            "content": {"type": "string"}
        }, 
        "required": ["path", "content"]
    }

    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        path = kwargs["path"]
        content = kwargs.get("content")

        try:
            fp = safe_path(path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"

# 这几个tool返回都是str，是因为模型只接受str吗 不是 是简化
# 精确结构（很重要） 比如： AST 表格数据 JSON API 响应 代码分析结果 ❗让模型做“程序级推理” 比如： 多步骤规划 状态机 structured tool chaining 这时候才应该： 👉 返回 JSON / dict，而不是纯字符串
# 上述简化成输入llm的是有结构的json？可是这最终不也是转成str加入模型上下文？还是模型内部怎么处理这个json数组结构？
# 是的，最终都会变成字符串（token序列）进入模型
# 但“结构化 JSON”的意义不在于内部存储，而在于token组织方式 + schema约束 + 语义分隔