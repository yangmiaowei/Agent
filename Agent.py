import json5

from LLM import OllamaChat
from tools import Tools

from prompt import TOOL_DESC, REACT_PROMPT


class Agent:
    def __init__(self) -> None:
        self.tool = Tools()
        self.system_prompt = self.build_system_input()
        self.model = OllamaChat()

    def build_system_input(self) -> str:
        tool_descs, tool_names = [], []
        for tool in self.tool.toolConfig:
            tool_descs.append(TOOL_DESC.format(**tool))
            tool_names.append(tool['name_for_model'])
        tool_descs = '\n\n'.join(tool_descs)
        tool_names = ','.join(tool_names)
        sys_prompt = REACT_PROMPT.format(tool_descs=tool_descs, tool_names=tool_names)
        return sys_prompt

    def parse_latest_plugin_call(self, text):
        plugin_name, plugin_args = '', ''
        i = text.rfind('\nAction:')
        j = text.rfind('\nAction Input:')
        k = text.rfind('\nObservation:')
        if 0 <= i < j:
            if k < j:
                text = text.rstrip() + '\nObservation:'
            k = text.rfind('\nObservation:')
            plugin_name = text[i + len('\nAction:') : j].strip()
            plugin_args = text[j + len('\nAction Input:') : k].strip()
            text = text[:k]
        return plugin_name, plugin_args, text

    def call_plugin(self, plugin_name, plugin_args):
        plugin_args = json5.loads(plugin_args)
        def build_args(tool, user_inputs: list):
            """
            根据工具的参数定义和用户输入生成字典
            tool.parameters: [{"q": "搜索关键词或短语"}]
            user_inputs: ["今天几号"]
            """
            args = {}
            for i, param_def in enumerate(tool.parameters):
                # param_def 是 {"q": "搜索关键词或短语"}
                for key in param_def:
                    args[key] = user_inputs[i]
            return args
        print("plugin_name:", plugin_name)
        print("plugin_args:", plugin_args)
        if plugin_name == 'search':
            return '\nObservation:' + self.tool.run(plugin_name, **plugin_args)
        if plugin_name == 'datetime':
            return '\nObservation:' + self.tool.run(plugin_name, **plugin_args)

    def text_completion(self, text, history=[]):
        text = '\nQuestion:' + text
        response, his = self.model.chat(text, history, self.system_prompt)
        print(response)
        plugin_name, plugin_args, response = self.parse_latest_plugin_call(response)
        if plugin_name:
            response += str(self.call_plugin(plugin_name, plugin_args))
        response, his = self.model.chat(response, history, self.system_prompt)
        return response, his

if __name__ == '__main__':
    agent = Agent()
    response, _ = agent.text_completion(text='今天是几月几号？', history=[])
    print(response)