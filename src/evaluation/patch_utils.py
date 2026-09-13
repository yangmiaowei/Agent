"""Helpers for inspecting unified diffs."""

TEST_PATH_MARKERS = ("test_", "_test", "/tests/", "tests/", "/test/", "conftest.py")


def patch_files(patch: str) -> list[str]:
    """Paths touched by a unified diff, in order of appearance."""
    files: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        # Example: diff --git a/path/file.py b/path/file.py
        parts = line.split()
        if len(parts) >= 4 and parts[2].startswith("a/"):
            files.append(parts[2][2:])
    return files


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in TEST_PATH_MARKERS)


def patch_stats(patch: str) -> dict:
    lines = patch.splitlines()
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    files = patch_files(patch)
    return {
        "files": files,
        "n_files": len(files),
        "added_lines": added,
        "removed_lines": removed,
        "hunks": sum(1 for l in lines if l.startswith("@@")),
        "bytes": len(patch),
        "source_files": [f for f in files if not is_test_path(f)],
        "test_files": [f for f in files if is_test_path(f)],
    }
