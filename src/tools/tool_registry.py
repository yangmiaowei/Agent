# class ToolRegistry:
#     _tools = {}

#     @classmethod
#     def register(cls, tool_class):
#         instance = tool_class()

#         name = instance.name
#         if name in cls._tools:
#             raise ValueError(f"Tool name conflict: {name}")

#         cls._tools[name] = instance
#         return tool_class

#     @classmethod
#     def get(cls, name: str):
#         tool = cls._tools.get(name)
#         if tool is None:
#             raise ValueError(f"Tool not found: {name}")
#         return tool
    
#     @classmethod
#     def call(cls, name: str, args: dict):
#         return cls.get(name).run(**args)

#     @classmethod
#     def all_schemas(cls):
#         return [t.schema() for t in cls._tools.values()]

# | 能力      | ToolRegistry | ToolManager |
# | ------- | ------------ | ----------- |
# | 多实例隔离   | ❌ 不支持        | ✅ 支持        |
# | 单例全局访问  | ✅            | ❌           |
# | 测试隔离    | 差            | 好           |
# | 多 agent | 不适合          | 适合          |
# | 插件系统    | 可以但危险        | 更自然         |



# -- The dispatch map: {tool_name: handler} --

# 把“带关键字参数的函数调用”包装成一个统一的处理入口
# lambda **kw：接收任意数量的关键字参数，并把它们打包成一个字典 kw
# kw["command"]：从参数字典里取出 "command"，只把它传给 run_bash

# TOOL_HANDLERS = {
#     "bash": lambda **kw: run_bash(kw["command"]),
# }
# 等价于：
# def bash_handler(**kw):
#     return run_bash(kw["command"])
# 只是写成了匿名函数版本 + 字典映射

# 典型的 工具分发器 / strategy pattern（策略模式）简化版
# 它的作用：用字符串选择函数：TOOL_HANDLERS["bash"]
# 所有工具统一调用方式：handler(**tool_args)

# lambda **kw: run_bash(kw["command"])
# “接收一堆参数 → 从里面挑 command → 调 run_bash”
# TOOL_HANDLERS = {
#     "bash":       lambda **kw: run_bash(kw["command"]),
#     "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
#     "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
#     "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
# }