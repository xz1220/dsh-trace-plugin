"""Cleanup removes reproducible artifacts while preserving source and local work."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/clean.py"


class CleanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git(self.root, "init", "-q")
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/clean.py")

    @staticmethod
    def git(directory, *arguments):
        return subprocess.run(
            ["git", "-C", str(directory), *arguments], check=True, capture_output=True, text=True
        )

    def write(self, name, text="keep"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_clean(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.root / "scripts/clean.py"), *arguments],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_source_recordings_and_tracked_artifacts_survive(self):
        source = self.write("plugins/trace/server/main.py")
        original = self.write("local-context/recordings/private.json")
        installed = self.write("plugins/trace/assets/viewer.html")
        configuration = self.write(".coveragerc")
        tracked = self.write("dist/reviewed.zip")
        self.git(self.root, "add", "dist/reviewed.zip")
        self.write(".cache/results.json")
        self.write("tests/__pycache__/test.pyc")
        (self.root / "plugins/trace/empty").mkdir()
        result = self.run_clean()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tracked files", result.stderr)
        self.assertTrue(
            all(path.exists() for path in (source, original, installed, tracked, configuration))
        )
        self.assertFalse((self.root / ".cache").exists())
        self.assertFalse((self.root / "tests/__pycache__").exists())
        self.assertFalse((self.root / "plugins/trace/empty").exists())

    def test_dependencies_are_opt_in_and_symlinks_do_not_delete_destinations(self):
        dependency = self.write("node_modules/library/index.js")
        environment = self.write(".venv/bin/python")
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside)
        original = outside / "original.txt"
        original.write_text("preserve")
        (self.root / ".cache").symlink_to(outside, target_is_directory=True)
        result = self.run_clean()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(original.exists())
        self.assertFalse((self.root / ".cache").is_symlink())
        self.assertTrue(dependency.exists())
        self.assertTrue(environment.exists())
        result = self.run_clean("--dependencies")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(dependency.exists())
        self.assertFalse(environment.exists())

    def test_bare_repository_is_preserved_when_status_cannot_verify_it(self):
        repository = self.root / ".cache/bare.git"
        repository.mkdir(parents=True)
        self.git(repository, "init", "--bare", "-q")
        result = self.run_clean()
        self.assertEqual(result.returncode, 1)
        self.assertTrue((repository / "HEAD").exists())
        self.assertIn("unclean Git checkout", result.stderr)

    def test_dirty_or_ignored_upstream_files_protect_the_checkout(self):
        upstream = self.root / ".cache/upstream"
        upstream.mkdir(parents=True)
        self.git(upstream, "init", "-q")
        tracked = self.write(".cache/upstream/source.txt", "original")
        self.write(".cache/upstream/.gitignore", "ignored.txt\n")
        self.git(upstream, "add", "source.txt", ".gitignore")
        self.git(
            upstream,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        for name in ("source.txt", "new.txt", "ignored.txt"):
            with self.subTest(name=name):
                changed = self.write(".cache/upstream/" + name, "changed")
                self.write("coverage/results.json")
                result = self.run_clean()
                self.assertEqual(result.returncode, 1)
                self.assertIn("unclean Git checkout", result.stderr)
                self.assertTrue(changed.exists())
                self.assertFalse((self.root / "coverage").exists())
                if changed == tracked:
                    changed.write_text("original")
                else:
                    changed.unlink()
        result = self.run_clean()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(upstream.exists())


if __name__ == "__main__":
    unittest.main()
