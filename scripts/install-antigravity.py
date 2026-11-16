#!/usr/bin/env python3
"""Install this worktree's Antigravity plugin without editing user settings."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ID = 'antigravity-dsh-trace'
MANAGER = 'codex-dsh-trace/antigravity-installer-v1'
SOURCE = Path(__file__).resolve().parents[1] / 'plugins' / PLUGIN_ID
MARKER = '.installation.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned(destination):
    if destination.is_symlink():
        raise ValueError('Refusing to replace a symlink: ' + str(destination))
    if destination.exists():
        marker = destination / MARKER
        try:
            data = json.loads(marker.read_text())
        except (OSError, ValueError):
            raise ValueError('Existing plugin is not managed by this installer: ' + str(destination))
        if data.get('managedBy') != MANAGER:
            raise ValueError('Existing plugin belongs to a different installer: ' + str(destination))


def backup_path(destination):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    return destination.parent.parent / 'plugin-backups' / PLUGIN_ID / stamp


def payload():
    required = ['plugin.json', 'assets/viewer.html', 'server/main.py',
                'server/native_store.py', 'sidecars/trace-viewer/sidecar.json',
                'sidecars/trace-viewer/main.mjs', 'sidecars/trace-viewer/rpc-client.mjs',
                'sidecars/trace-viewer/tool-request.mjs', 'sidecars/trace-viewer/host.html',
                'sidecars/trace-viewer/host.js']
    for relative in required:
        if not (SOURCE / relative).is_file():
            raise ValueError('Missing ' + relative + '; run npm run build:antigravity first.')
    files = {}
    for root in [SOURCE / 'plugin.json', SOURCE / 'assets', SOURCE / 'server', SOURCE / 'sidecars']:
        for path in ([root] if root.is_file() else root.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.log'):
                continue
            if path.is_symlink():
                raise ValueError('Plugin payload cannot contain symlinks: ' + str(path))
            if path.is_file() and path.suffix in ('.json', '.py', '.mjs', '.js', '.html', '.css', '.svg'):
                files[path.relative_to(SOURCE).as_posix()] = digest(path)
    if (SOURCE / 'README.md').is_file():
        files['README.md'] = digest(SOURCE / 'README.md')
    return files


def install(destination, *, uninstall=False, dry_run=False):
    destination = destination.expanduser().absolute()
    if destination.name != PLUGIN_ID:
        raise ValueError('Destination directory must be named ' + PLUGIN_ID)
    owned(destination)
    previous = backup_path(destination) if destination.exists() else None
    if uninstall:
        result = {'action': 'uninstall', 'path': str(destination),
                  'backup': str(previous) if previous else None, 'dryRun': dry_run}
        if previous and not dry_run:
            previous.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(previous)
        return result
    files = payload()
    manifest = json.loads((SOURCE / 'plugin.json').read_text())
    result = {'action': 'install', 'path': str(destination), 'version': manifest.get('version'),
              'files': len(files), 'backup': str(previous) if previous else None, 'dryRun': dry_run}
    result['reloadRequired'] = previous is not None
    if dry_run:
        return result
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.antigravity-trace-', dir=destination.parent.parent) as temporary:
        staged = Path(temporary) / PLUGIN_ID
        staged.mkdir()
        for relative, checksum in files.items():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / relative, target)
            if digest(target) != checksum:
                raise ValueError('Installed file verification failed: ' + relative)
        (staged / MARKER).write_text(json.dumps({
            'managedBy': MANAGER, 'version': manifest.get('version'), 'files': files,
            'installedAt': datetime.now(timezone.utc).isoformat(),
        }, indent=2) + '\n')
        if previous:
            previous.parent.mkdir(parents=True, exist_ok=True)
            destination.rename(previous)
        try:
            staged.rename(destination)
        except OSError:
            if previous:
                previous.rename(destination)
            raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path,
                        default=Path.home() / '.gemini/config/plugins' / PLUGIN_ID)
    parser.add_argument('--uninstall', action='store_true', help='Move the managed installation to backups.')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        result = install(args.destination, uninstall=args.uninstall, dry_run=args.dry_run)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
