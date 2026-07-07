from src.logger.logger import log_message
from src.orchestrator.base_loop import BaseLoop
from src.runtime.context import RuntimeContext

from src.memory.context_compactor import estimate_tokens, micro_compact, auto_compact


class CompactLoop(BaseLoop):
    """BaseLoop with context compact."""

    def __init__(
        self,
        *args,
        compact_threshold: int = 50000,
        keep_recent: int = 3,
        preserve_result_tools: list[str] | None = None,
        transcript_dir: str = ".transcripts",
        summary_max_tokens: int = 2000,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.compact_threshold = compact_threshold
        self.keep_recent = keep_recent
        self.preserve_result_tools = (
            preserve_result_tools
            if preserve_result_tools is not None
            else ["read_file", "grep"]
        )
        self.transcript_dir = transcript_dir
        self.summary_max_tokens = summary_max_tokens

    
    def loop(self, messages: list, logger=None, max_rounds: int | None = None):
        ctx = RuntimeContext(messages=messages)
        turn = 0

        while True:
            if max_rounds is not None and turn >= max_rounds:
                return
            turn += 1

            # Layer 1: micro_compact before each LLM call
            micro_compact(messages)
            # Layer 2: auto_compact if token estimate exceeds threshold
            if estimate_tokens(messages) > self.compact_threshold:
                print("[auto_compact triggered]")
                messages[:] = auto_compact(messages, self.transcript_dir)

            resolved = self.runtime.resolve(ctx)
            response = self.agent.run(
                messages,
                tools=resolved.tool_view,
                system=resolved.system_prompt,
            )
            assistant_msg = {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content],
            }
            messages.append(assistant_msg)
            log_message(logger, assistant_msg)

            if response.stop_reason != "tool_use":
                return

            results = []
            manual_compact = False
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "compact":
                        manual_compact = True
                        output = "Compression requested."
                    else:
                        try:
                            output = self.executor.run(
                                block.name,
                                block.input,
                                ctx,
                                resolved.tool_view,
                            )
                        except Exception as e:
                            output = f"Error: {e}"
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
                
            user_msg = {"role": "user", "content": results}
            messages.append(user_msg)
            log_message(logger, user_msg)
            ctx.round_idx += 1

            if manual_compact:
                print("[manual compact]")
                messages[:] = auto_compact(messages, self.transcript_dir)
                return



# def agent_loop(messages: list):
#     while True:
#         # Layer 1: micro_compact before each LLM call
#         micro_compact(messages)
#         # Layer 2: auto_compact if token estimate exceeds threshold
#         if estimate_tokens(messages) > THRESHOLD:
#             print("[auto_compact triggered]")
#             messages[:] = auto_compact(messages)  # 把 messages 这个列表里的内容，原地替换成新的内
#         response = client.messages.create(
#             model=MODEL,
#             system=SYSTEM,
#             messages=messages,
#             tools=TOOLS,
#             max_tokens=8000
#         )
#         messages.append({"role": "assistant", "content": response.content})
#         if response.stop_reason != "tool_use":
#             return
#         results = []
#         manual_compact = False
#         for block in response.content:
#             if block.type == "tool_use":
#                 if block.name == "compact":
#                     manual_compact = True
#                     output = "Compressing..."
#                 else:
#                     handler = TOOL_HANDLERS.get(block.name)
#                     try:
#                         output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
#                     except Exception as e:
#                         output = f"Error: {e}"
#                 print(f"> {block.name}:")
#                 print(str(output[:200]))
#                 results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
#         messages.append({"role": "user", "content": results})
#         # Layer 3: manual compact triggered by the compact tool
#         if manual_compact:
#             print("[manual compact]")
#             messages[:] = auto_compact(messages)
#             return

#     "compact":    lambda **kw: "Manual compression requested.",
# }