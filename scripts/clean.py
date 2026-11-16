"""Remove regenerable project artifacts without touching source or local recordings."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    ".cache",
    "dist",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    "htmlcov",
    "playwright-report",
    "test-results",
)
SOURCE_ROOTS = ("plugins", "scripts", "tests")


def directories(root):
    """Walk real directories only; never enter Git metadata or linked trees."""
    for current, names, _ in os.walk(root, followlinks=False):
        path = Path(current)
        names[:] = [name for name in names if name != ".git" and not (path / name).is_symlink()]
        yield path


def clean(dependencies=False):
    try:
        checkout = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"], text=True
        ).strip()
        if Path(checkout).resolve() != ROOT:
            raise ValueError("project root is not a Git checkout")
        tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"])
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Cannot inspect tracked files; nothing was removed.", file=sys.stderr)
        return 1
    tracked_paths = {os.fsdecode(path) for path in tracked.split(b"\0") if path}
    failed = False

    def remove(path):
        nonlocal failed
        if not path.exists() and not path.is_symlink():
            return
        relative = path.relative_to(ROOT).as_posix()
        if any(name == relative or name.startswith(relative + "/") for name in tracked_paths):
            print(f"Skipped {relative}: contains tracked files.", file=sys.stderr)
            failed = True
            return
        # A link itself is disposable; its destination is outside this operation.
        if path.is_dir() and not path.is_symlink():
            for directory in directories(path):
                marker = directory / ".git"
                bare = all((directory / name).exists() for name in ("HEAD", "objects", "refs"))
                if not marker.exists() and not marker.is_symlink() and not bare:
                    continue
                try:
                    if marker.is_symlink():
                        raise ValueError("linked Git metadata")
                    status = subprocess.check_output(
                        [
                            "git",
                            "-C",
                            str(directory),
                            "status",
                            "--porcelain=v1",
                            "--untracked-files=all",
                            "--ignored",
                        ],
                        stderr=subprocess.DEVNULL,
                    )
                    if status:
                        raise ValueError("repository has local files or changes")
                except (OSError, ValueError, subprocess.CalledProcessError):
                    print(f"Skipped {relative}: contains an unclean Git checkout.", file=sys.stderr)
                    failed = True
                    return
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            print(f"Removed {relative}")
        except OSError as error:
            print(f"Skipped {relative}: {error.strerror}.", file=sys.stderr)
            failed = True

    targets = [ROOT / name for name in ARTIFACTS]
    targets.append(ROOT / ".coverage")
    targets.extend(ROOT.glob(".coverage.*"))
    if dependencies:
        targets.extend(ROOT / name for name in ("node_modules", ".venv"))
    for target in targets:
        remove(target)
    for name in SOURCE_ROOTS:
        root = ROOT / name
        if not root.is_dir() or root.is_symlink():
            continue
        # Collect first because deletion changes the directory walk.
        for path in list(directories(root)):
            cache = path / "__pycache__"
            if cache.exists() or cache.is_symlink():
                remove(cache)
        for path in reversed(list(directories(root))):
            if path != root and not any(path.iterdir()):
                try:
                    path.rmdir()
                except OSError as error:
                    print(f"Skipped {path.relative_to(ROOT)}: {error.strerror}.", file=sys.stderr)
                    failed = True
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dependencies", action="store_true", help="Also remove node_modules and .venv"
    )
    raise SystemExit(clean(parser.parse_args().dependencies))
