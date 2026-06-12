def build_task_prompt(instance: dict) -> str:
    return f"""You are tasked with fixing a bug in an open-source repository.

Repository: {instance["repo"]}
Instance: {instance["instance_id"]}

<problem_statement>
{instance["problem_statement"]}
</problem_statement>

Investigate the issue, make the necessary code changes to fix it, and verify your fix when possible.
Only modify source files required to fix the issue. Do not modify test files unless necessary for the fix.
"""
