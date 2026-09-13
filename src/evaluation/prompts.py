def build_task_prompt(instance: dict, *, strict: bool = False) -> str:
    problem = instance.get("problem_statement") or ""

    prompt = f"""You are tasked with fixing a bug in an open-source repository.

Repository: {instance["repo"]}
Instance: {instance["instance_id"]}
Working directory: the repository root (use relative paths from here).

<problem_statement>
{problem}
</problem_statement>

Instructions:
1. Use bash/grep to locate relevant files, then read_file with offset/limit for specific sections.
2. Apply the fix with edit_file by modifying existing tracked source files.
3. Do NOT create standalone reproduction scripts or new test files in the repo root.
4. Make the minimal change needed to fix the issue described above.
5. You must edit at least one existing source file before finishing.
6. When done, briefly summarize which files you changed and why.
"""
    if strict:
        prompt += """

Critical constraints for this attempt:
- You must produce at least one edit to existing tracked source files.
- Do not spend turns creating standalone scripts or broad repo exploration.
- If runtime dependencies are missing, still implement a source patch based on static analysis.
- Prefer a minimal patch over extensive investigation.
"""
    return prompt
