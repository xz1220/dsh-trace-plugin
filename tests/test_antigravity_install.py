import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'antigravity_installer', Path(__file__).resolve().parents[1] / 'scripts/install-antigravity.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class AntigravityInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        self.target = root / 'config/plugins' / installer.PLUGIN_ID
        for relative in ['assets/viewer.html', 'server/main.py', 'server/native_store.py',
                         'sidecars/trace-viewer/sidecar.json', 'sidecars/trace-viewer/main.mjs',
                         'sidecars/trace-viewer/rpc-client.mjs', 'sidecars/trace-viewer/tool-request.mjs',
                         'sidecars/trace-viewer/host.html', 'sidecars/trace-viewer/host.js']:
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if path.suffix == '.json' else 'version one')
        (self.source / 'plugin.json').write_text(json.dumps({'name': installer.PLUGIN_ID, 'version': '0.1.0'}))
        self.mock = patch.object(installer, 'SOURCE', self.source)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_unknown_existing_plugin_is_preserved(self):
        self.target.mkdir(parents=True)
        user_file = self.target / 'important.txt'
        user_file.write_text('user work')
        with self.assertRaisesRegex(ValueError, 'not managed'):
            installer.install(self.target)
        self.assertEqual(user_file.read_text(), 'user work')

    def test_upgrade_keeps_the_previous_installation_and_verifies_payload(self):
        installer.install(self.target)
        (self.target / 'user-notes.txt').write_text('preserve me')
        (self.source / 'assets/viewer.html').write_text('version two')
        result = installer.install(self.target)
        backup = Path(result['backup'])
        self.assertEqual((backup / 'user-notes.txt').read_text(), 'preserve me')
        self.assertEqual((backup / 'assets/viewer.html').read_text(), 'version one')
        self.assertEqual((self.target / 'assets/viewer.html').read_text(), 'version two')
        marker = json.loads((self.target / installer.MARKER).read_text())
        for relative, checksum in marker['files'].items():
            self.assertEqual(installer.digest(self.target / relative), checksum)

    def test_dry_run_does_not_create_a_plugin_and_uninstall_is_recoverable(self):
        installer.install(self.target, dry_run=True)
        self.assertFalse(self.target.exists())
        installer.install(self.target)
        result = installer.install(self.target, uninstall=True)
        self.assertFalse(self.target.exists())
        self.assertTrue((Path(result['backup']) / 'plugin.json').is_file())

    def test_private_runtime_files_and_symlinks_are_not_packaged(self):
        (self.source / 'server/private.jsonl').write_text('private transcript')
        (self.source / 'server/.env').write_text('private environment')
        installer.install(self.target)
        self.assertFalse((self.target / 'server/private.jsonl').exists())
        self.assertFalse((self.target / 'server/.env').exists())
        (self.source / 'server/link.py').symlink_to(self.source / 'server/main.py')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            installer.install(self.target)


if __name__ == '__main__':
    unittest.main()
