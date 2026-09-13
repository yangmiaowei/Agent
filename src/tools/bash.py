import subprocess

from src.tools.base_tool import BaseTool
from src.tools.bash_policy import get_bash_policy
from src.workspace import get_workdir


class Bash(BaseTool):
    name = "bash"
    description = "Run a shell command."
    input_schema = {
        "type": "object",
        "properties": {  # 定义有哪些参数
            "command": {"type": "string"}  # command 必须是字符串
        },
        "required": ["command"]
    }

    def run(self, **kwargs) -> str:
        # 校验参数
        self.validate(kwargs)

        command = kwargs["command"]

        # 危险/越界命令过滤。规则随 runtime mode 变化，见 bash_policy。
        policy = get_bash_policy()
        violation = policy.violation(command)
        if violation:
            return f"Error: {violation}"

        try:
            r = subprocess.run(  # 启动一个子进程执行 command，等它执行完，然后返回结果对象 r
                command, 
                shell=True,  # 通过 shell（比如 /bin/bash）来执行命令，有命令注入风险
                cwd=get_workdir(),
                # swe 模式下把 HOME/TMPDIR 等指向临时目录，见 BashPolicy.environ
                env=policy.environ(),
                capture_output=True,  # 把 stdout 和 stderr 都抓回来，否则输出会直接打印到终端 拿不到结果
                text=True, #把输出从 bytes → 字符串 否则你拿到的是：b'hello\n'，加了之后变成："hello\n"
                timeout=policy.timeout  # 防止：死循环，卡死，挂住 agent
            )

            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"

        except subprocess.TimeoutExpired:
            return f"Error: Timeout ({policy.timeout}s)"
