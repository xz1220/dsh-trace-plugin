#!/usr/bin/env python3
"""Launch Codex with official rollout tracing enabled for this child process."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--trace-root',type=Path,default=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'rollout-traces')
parser.add_argument('--desktop-env',action='store_true',help='Enable tracing for macOS apps launched after this command, for the current login session; does not restart Codex')
parser.add_argument('codex_args',nargs=argparse.REMAINDER)
args=parser.parse_args()
root=args.trace_root.expanduser().resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
if args.desktop_env:
    if sys.platform!='darwin':parser.error('--desktop-env requires macOS')
    if args.codex_args:parser.error('--desktop-env does not accept Codex CLI arguments')
    subprocess.run(['launchctl','setenv','CODEX_ROLLOUT_TRACE_ROOT',str(root)],check=True)
    print('Desktop recording configured. Fully quit and reopen Codex. Existing chats cannot be recorded retroactively.')
    raise SystemExit(0)
env=dict(os.environ);env['CODEX_ROLLOUT_TRACE_ROOT']=str(root)
arguments=args.codex_args[1:] if args.codex_args[:1]==['--'] else args.codex_args
raise SystemExit(subprocess.call(['codex',*arguments],env=env))
