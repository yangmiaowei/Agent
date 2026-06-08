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