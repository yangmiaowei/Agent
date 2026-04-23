import serpapi

from Tools.base_tool import BaseTool


class SearchTool(BaseTool):
    name_for_human = "搜索"
    name_for_model = "search"
    description_for_model = "通用搜索引擎，可用于访问互联网、查询百科知识、了解时事新闻等。"
    parameters = [{"q": "搜索关键词或短语"}]

    def run(self, q: str):
        params = {
            "engine": "google",
            "q": q,
            "api_key": "1f0c8bc4511b9e861c6889c41ba2213440a2ecadcc681b61e2242b44361fb741"
        }
        result = serpapi.search(params)
        return{"search_result:", result}