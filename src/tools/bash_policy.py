"""Execution policy for the `bash` tool, selected by runtime mode.

In `default` mode a human is driving and expects an ordinary shell, so bash
stays unconstrained apart from a few catastrophic commands.

`swe` mode is different: the agent runs unattended inside a benchmark
checkout, and the benchmark's whole premise is that every instance starts
from an identical environment. A single `pip install -e .` breaks that -- it
rewrites the host interpreter's site-packages, so the repo under test leaks
into every later run and into unrelated projects sharing the interpreter.
That is exactly what happened during the suite_v1 baseline: the agent
installed pytest, sphinx and xarray from `eval_repos/` into the shared conda
environment, replacing the real packages.

Two layers guard against it:

  1. A denylist that rejects environment-mutating commands up front, with a
     message telling the agent what to do instead.
  2. Environment overrides that make host-wide writes fail even when a
     command slips through layer 1 (a Makefile target invoking pip, say).

This is containment, not a kernel sandbox. A command that really wants to
escape still can -- `python -c` can write anywhere the user can. The goal is
to close the failure modes that actually occur and make the rest loud.
"""

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Rules applied in every mode. These are unrecoverable, not merely dirty.
_UNIVERSAL_RULES: tuple[tuple[str, str], ...] = (
    (r"^(?:shutdown|reboot|halt|poweroff)\b", "cannot control the host machine"),
    # `rm -rf /`, `rm -rf ~`, `rm -rf $HOME` and flag permutations thereof.
    (
        r"^rm\s+(?:-\S+\s+)*(?:/|~|\$HOME|\$\{HOME\})\s*$",
        "refusing to delete a filesystem root or home directory",
    ),
    (r"^\s*>\s*/dev/(?:sd|disk|nvme|rdisk)", "cannot write to raw block devices"),
)

#: Additional rules for unattended benchmark runs.
_SWE_RULES: tuple[tuple[str, str], ...] = (
    (
        r"^(?:sudo|doas)\b",
        "sudo is not available; the environment is already set up",
    ),
    (
        r"^(?:\S*python[\d.]*\s+-m\s+)?pip[\d.]*\s+(?:install|uninstall|download)\b",
        "installing packages is blocked: the repository and its dependencies "
        "are already installed for this interpreter. Import and test the "
        "checkout directly, e.g. `python -m pytest <path>`",
    ),
    (
        r"^uv\s+(?:pip\s+)?(?:install|uninstall|add|remove|sync)\b",
        "installing packages is blocked: the environment is already set up",
    ),
    (
        r"^(?:conda|mamba|micromamba)\s+(?:install|remove|uninstall|update|"
        r"upgrade|env|create)\b",
        "changing the conda environment is blocked: it is shared with other "
        "runs and with the harness",
    ),
    (
        r"^poetry\s+(?:install|add|remove|update)\b",
        "installing packages is blocked: the environment is already set up",
    ),
    (
        r"^(?:\S*python[\d.]*\s+)?setup\.py\b.*\b(?:install|develop)\b",
        "`setup.py install/develop` rewrites site-packages; the checkout is "
        "already importable",
    ),
    (
        r"^(?:apt|apt-get|yum|dnf|brew|port|pacman|snap)\b",
        "system package managers are not available",
    ),
    (
        r"^(?:npm|yarn|pnpm)\s+(?:install|i|add)\b(?:.*\s)?-{1,2}g(?:lobal)?\b",
        "global npm installs are blocked",
    ),
    (
        r"^git\s+config\s+(?:--global|--system)\b",
        "cannot change global git configuration; use `-c key=value` for a "
        "single command instead",
    ),
)

#: Shell operators that start a new command. `&` is included so that
#: `pip install ... &` cannot smuggle a rule past the head match.
_SEGMENT_BOUNDARY = re.compile(r"\|\||&&|[;\n|&()]")

#: Leading `FOO=bar` assignments belong to the command, not to its name.
_LEADING_ASSIGNMENT = re.compile(r"^\s*(?:\w+=(?:\"[^\"]*\"|'[^']*'|\S*)\s+)+")


def _segments(command: str) -> list[str]:
    """Split a command line into the individual commands it will run.

    Matching rules against each segment's head (rather than searching the
    whole line) is what keeps `grep -r "pip install" docs/` allowed while
    `cd src && pip install -e .` is not.
    """
    parts = []
    for raw in _SEGMENT_BOUNDARY.split(command):
        segment = _LEADING_ASSIGNMENT.sub("", raw).strip()
        if segment:
            parts.append(segment)
    return parts


@dataclass(frozen=True)
class BashPolicy:
    name: str
    #: (compiled pattern, reason) pairs matched against each command segment.
    rules: tuple[tuple[re.Pattern, str], ...]
    #: Extra environment variables for the subprocess.
    env_overrides: dict[str, str] = field(default_factory=dict)
    #: Redirect HOME/TMPDIR into a scratch directory outside the workspace.
    isolate_home: bool = False
    timeout: int = 120

    def violation(self, command: str) -> str | None:
        """The reason `command` is rejected, or None when it may run."""
        for segment in _segments(command):
            for pattern, reason in self.rules:
                if pattern.search(segment):
                    return reason
        return None

    def environ(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.isolate_home:
            scratch = scratch_dir()
            env["HOME"] = str(scratch)
            env["TMPDIR"] = str(scratch / "tmp")
            # Keep the agent out of the user's git identity and hooks even if
            # it bypasses the `git config --global` rule.
            env["GIT_CONFIG_GLOBAL"] = str(scratch / "gitconfig")
            env["GIT_CONFIG_SYSTEM"] = os.devnull
            Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
        env.update(self.env_overrides)
        return env


def _compile(*rule_groups: tuple[tuple[str, str], ...]) -> tuple[tuple[re.Pattern, str], ...]:
    return tuple(
        (re.compile(pattern, re.IGNORECASE), reason)
        for group in rule_groups
        for pattern, reason in group
    )


DEFAULT_POLICY = BashPolicy(
    name="default",
    rules=_compile(_UNIVERSAL_RULES, ((r"^(?:sudo|doas)\b", "sudo is blocked"),)),
)

SWE_POLICY = BashPolicy(
    name="swe",
    rules=_compile(_UNIVERSAL_RULES, _SWE_RULES),
    env_overrides={
        # Defence in depth: if a build script calls pip anyway, refuse rather
        # than write into the interpreter shared with the harness.
        "PIP_REQUIRE_VIRTUALENV": "1",
        "PIP_NO_INPUT": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        # Never fall back to ~/.local/lib/pythonX.Y/site-packages.
        "PYTHONNOUSERSITE": "1",
        # Tests that shell out must inherit the same policy.
        "AGENT_MODE": "swe",
    },
    isolate_home=True,
)

_POLICIES = {"swe": SWE_POLICY}

_active_policy: BashPolicy | None = None
_scratch_dir: Path | None = None


def policy_for_mode(mode: str) -> BashPolicy:
    return _POLICIES.get(mode, DEFAULT_POLICY)


def set_bash_policy(policy: BashPolicy) -> None:
    global _active_policy
    _active_policy = policy


def get_bash_policy() -> BashPolicy:
    return _active_policy if _active_policy is not None else DEFAULT_POLICY


def scratch_dir() -> Path:
    """Throwaway HOME for isolated runs.

    Deliberately outside the workspace: the workspace is a git checkout whose
    diff becomes the submitted patch, and `reset_repo` runs `git clean -fdx`
    between attempts, which would wipe anything stored there.
    """
    global _scratch_dir
    if _scratch_dir is None or not _scratch_dir.exists():
        _scratch_dir = Path(tempfile.mkdtemp(prefix="agent-bash-home-"))
    return _scratch_dir


def reset_bash_policy() -> None:
    """Restore the default policy and discard the scratch HOME."""
    global _active_policy, _scratch_dir
    _active_policy = None
    if _scratch_dir is not None:
        shutil.rmtree(_scratch_dir, ignore_errors=True)
        _scratch_dir = None
