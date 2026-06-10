from src.tools.tool_manager import ToolManager
from src.tools.tool_loader import load_all_tools, load_subagent_tools
from src.model.AnthropicClient import AnthropicClient
from src.agent.base_agent import BaseAgent
from src.runtime.base_loop import BaseLoop
from src.logger.logger import JsonLogger, log_message

logger = JsonLogger()

tool_manager = ToolManager()
load_all_tools(tool_manager)

subagent_tool_manager = ToolManager()
load_subagent_tools(subagent_tool_manager)

client = AnthropicClient(tools=tool_manager)
agent = BaseAgent(client=client)
agent_loop = BaseLoop(agent=agent, tools=tool_manager)

# 修复 macOS 终端里 Python 输入中文 / 特殊字符 / 退格键异常的问题
try:
    import readline
    # #143 UTF-8 backspace fix for macOS libedit
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        user_msg = {"role": "user", "content": query}
        history.append(user_msg)
        log_message(logger, user_msg)
        agent_loop.loop(history, logger=logger)
