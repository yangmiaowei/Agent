import re
import yaml

# -- SkillLoader: scan skills/<name>/SKILL.md with YAML frontmatter --
class SkillLoader:
    def __init__(self, skill_dir: Path):
        self.skill_dir = skill_dir
        self.skills = {}
        self._load_all()
    
    def _load_all(self):
        if not self.skill_dir.exists():
            return
        for f in sorted(self.skill_dir.rglob("SKILL.md")):  # recursive glob 从skill_dir目录开始递归进入子目录查找文件，类似glob
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)  # name
            # 扫描所有 SKILL.md 文件 → 读取内容 → 解析元数据 → 注册成一个 skill 字典。
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}

    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between -- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}  # load
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f" - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:  # 结构化prompt
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {','.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"


SKILL_LOADER = SkillLoader(SKILL_DIR)

 "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),

 # Layer 1: skill metadata injected into system prompt
SYSTEM = f"""You are a coding agent at {WORKDIR}. 
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""



# skill = “延迟注入的上下文模块”

# 它不是：

# tool（会执行）
# prompt（一直存在）

# 而是：

# “当模型需要知识时，才加载进 context window”


# "用到什么知识, 临时加载什么知识" -- 通过 tool_result 注入, 不塞 system prompt。
# Harness 层: 按需知识 -- 模型开口要时才给的领域专长。

# agent本质是不是functioncall?
# agent 是“以 function call 为执行接口的循环决策系统”。
# 更本质是：agent = RL-style interaction loop