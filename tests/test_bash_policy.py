"""Policy tests for the bash tool. No LLM, no repos.

The blocked commands below are the ones the agent actually issued during the
suite_v1 baseline, which installed three benchmark checkouts into the shared
conda environment.
"""

import os
from pathlib import Path

import pytest

from src.tools.bash import Bash
from src.tools.bash_policy import (
    DEFAULT_POLICY,
    SWE_POLICY,
    policy_for_mode,
    reset_bash_policy,
    set_bash_policy,
)
from src.workspace import get_workdir, reset_workdir, set_workdir


@pytest.fixture(autouse=True)
def _clean_policy():
    yield
    reset_bash_policy()


# ---------------------------------------------------------------- denylist


@pytest.mark.parametrize("command", [
    "pip install -e .",
    "pip3 install -e .",
    "python -m pip install -e .",
    "/opt/anaconda3/bin/python -m pip install -e .",
    "pip install --no-build-isolation -e .",
    "pip uninstall -y xarray",
    "uv pip install -e .",
    "conda install -y pytest",
    "python setup.py develop",
    "python setup.py build_ext --inplace install",
    "poetry add requests",
    "apt-get install -y libfreetype6-dev",
    "sudo rm /etc/hosts",
    "git config --global user.email a@b.c",
])
def test_swe_mode_blocks_environment_mutation(command):
    assert SWE_POLICY.violation(command) is not None


@pytest.mark.parametrize("command", [
    "python -m pytest xarray/tests/test_merge.py -x",
    "python -c 'import xarray; print(xarray.__file__)'",
    "pip list | grep xarray",
    "pip show pytest",
    "git diff",
    "git -c user.email=a@b.c commit -m wip",
    "grep -rn 'pip install' docs/",
    "cat README.rst | head -40",
    "ls -la && pwd",
    "make -C doc html",
])
def test_swe_mode_allows_reading_and_testing(command):
    assert SWE_POLICY.violation(command) is None


def test_rule_matches_later_segments_not_just_the_first():
    # The real failure looked like this: an innocent `cd` hiding an install.
    assert SWE_POLICY.violation("cd /tmp && pip install -e .") is not None
    assert SWE_POLICY.violation("pytest -x; pip install -e .") is not None
    assert SWE_POLICY.violation("pip install -e . &") is not None


def test_leading_env_assignments_do_not_hide_the_command():
    assert SWE_POLICY.violation("PIP_NO_INPUT=1 pip install -e .") is not None
    assert SWE_POLICY.violation("CC=gcc pip install .") is not None


def test_default_mode_leaves_package_management_to_the_user():
    assert DEFAULT_POLICY.violation("pip install -e .") is None
    assert DEFAULT_POLICY.violation("conda install pytest") is None


@pytest.mark.parametrize("command", ["shutdown -h now", "rm -rf /", "rm -rf ~"])
def test_catastrophic_commands_are_blocked_in_every_mode(command):
    assert DEFAULT_POLICY.violation(command) is not None
    assert SWE_POLICY.violation(command) is not None


def test_rm_rf_of_a_normal_path_is_allowed():
    # Repos legitimately clean build output.
    assert SWE_POLICY.violation("rm -rf build/ dist/") is None


def test_policy_lookup_falls_back_to_default_for_unknown_modes():
    assert policy_for_mode("swe") is SWE_POLICY
    assert policy_for_mode("default") is DEFAULT_POLICY
    assert policy_for_mode("safe") is DEFAULT_POLICY


# ------------------------------------------------------- environment layer


def test_swe_env_refuses_pip_outside_a_virtualenv():
    env = SWE_POLICY.environ()
    assert env["PIP_REQUIRE_VIRTUALENV"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"


def test_swe_env_redirects_home_away_from_the_real_one(tmp_path):
    set_workdir(tmp_path)
    try:
        env = SWE_POLICY.environ()
        home = Path(env["HOME"])
        assert home != Path(os.path.expanduser("~"))
        # Must sit outside the workspace: the workspace is a git checkout whose
        # diff is submitted, and it gets `git clean -fdx`ed between attempts.
        assert not home.is_relative_to(get_workdir())
        assert Path(env["TMPDIR"]).is_dir()
    finally:
        reset_workdir()


def test_default_env_is_the_real_environment():
    env = DEFAULT_POLICY.environ()
    assert env["HOME"] == os.environ["HOME"]


# ------------------------------------------------------------- tool wiring


def test_tool_reports_the_reason_instead_of_running(tmp_path):
    set_workdir(tmp_path)
    set_bash_policy(SWE_POLICY)
    try:
        out = Bash().run(command="pip install -e .")
        assert out.startswith("Error:")
        assert "already installed" in out
    finally:
        reset_workdir()


def test_tool_runs_allowed_commands_under_the_isolated_home(tmp_path):
    set_workdir(tmp_path)
    set_bash_policy(SWE_POLICY)
    try:
        out = Bash().run(command="echo $HOME")
        assert out != os.environ["HOME"]
        assert "agent-bash-home-" in out
    finally:
        reset_workdir()
