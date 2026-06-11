from src.setup import build_main_runtime
from src.logger.logger import log_message

# tools 定义能力，setup 组装一切，入口只调一个函数。
agent_loop, logger = build_main_runtime()

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
