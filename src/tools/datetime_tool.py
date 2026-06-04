import datetime

from Tools.base_tool import BaseTool


class DatetimeTool(BaseTool):
    name_for_human = "日期和时间"
    name_for_model = "datetime"
    description_for_model = "获取当前日期和时间。"
    parameters = []

    def run(self):
        now = datetime.datetime.now()
        print({"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S")})
        return {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S")}