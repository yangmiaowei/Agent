
    

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
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"])
}



# -- The core pattern: a while loop that calls tools until the model stops --
def agent_loop(messages: list):
    while True:
        print("call llm:")
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000
        )
        print(response)
        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})
        # If the model didn't call a tool, we're done
        if response.stop_reason != "tool_use":
            return
        # Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # print(f"\033[33m$ {block.input['command']}\033[0m")
                # output = run_bash(block.input["command"])
                # print(output[:200])
                # results.append({
                #     "type": "tool_result",
                #     "tool_use_id": block.id,
                #     "content": output
                # })
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown tool: {block.name}"  # **的作用是把字典“解包成关键字参数”
                # print(f"> {block.name}:")
                # print(output[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})


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
        agent_loop(history)

        print("\n===== FULL MESSAGES DEBUG =====")
        for i, m in enumerate(history):
            print(f"\n--- message {i} ---")
            print(m)

        # response_content = history[-1]["content"]
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
        print()
