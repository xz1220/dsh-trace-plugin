"""Isolated recording setup shared by projection behavior tests."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from store import Store


class ProjectionFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        isolated = patch.dict(
            os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "environment-root")}
        )
        isolated.start()
        self.addCleanup(isolated.stop)
        self.fixture = Fixture(self.root / "bundle")
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "unused"
        self.store.catalog.register(str(self.fixture.root))

    def tearDown(self):
        self.temp.cleanup()

    def project(self):
        return self.store.projection("trace-test")
