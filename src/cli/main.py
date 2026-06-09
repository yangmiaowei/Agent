from src.runtime.baseloop import agent_loop
from src.tools.tool_loader import load_all_tools
from src.logger.logger import logger

load_all_tools()

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

        history.append({"role": "user", "content": query})
        agent_loop.loop(history)

        for msg in history:
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, list):
                for block in content:
                    logger.log({"role": role, "content": block})
            else:
                logger.log({"role": role, "content": content})