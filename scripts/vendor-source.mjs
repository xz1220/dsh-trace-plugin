import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';

// Validate before the importer writes anything. Mirrors and local clones are
// allowed: Git object identity, rather than a remote URL, pins the source.
export function verifyVendorSource(directory, { repository, commit }) {
  if (typeof repository !== 'string' || !repository || !/^[a-f0-9]{40}$/.test(commit))
    throw new Error('Vendor source must pin a repository and full commit hash.');
  const git = (...args) =>
    execFileSync('git', ['-C', directory, ...args], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
  if (realpathSync(directory) !== realpathSync(git('rev-parse', '--show-toplevel')))
    throw new Error('Vendor source directory must be the Git checkout root.');
  const actual = git('rev-parse', 'HEAD');
  if (actual !== commit)
    throw new Error(`Vendor source must be ${repository}@${commit}; found ${actual}.`);
  if (git('status', '--porcelain=v1', '--untracked-files=all'))
    throw new Error('Vendor source checkout must be clean, including untracked files.');
  return { repository, commit };
}
