#!/usr/bin/env python3
"""Play synthetic installer UI scenarios, without reading personal settings."""

import argparse
import json
import sys
import time
from pathlib import Path

from installer_ui import InstallerUI


class RecordingStream:
    def __init__(self):
        self.started = time.monotonic()
        self.events = []

    def isatty(self):
        return sys.stderr.isatty()

    def write(self, value):
        self.events.append([round(time.monotonic() - self.started, 3), value])
        return sys.stderr.write(value)

    def flush(self):
        sys.stderr.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", choices=("install", "repair", "unchanged", "error"), default="install"
    )
    parser.add_argument("--no-animation", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--record", type=Path, help="Save a synthetic terminal replay as JSON")
    args = parser.parse_args()
    stream = RecordingStream()
    ui = InstallerUI(stream=stream, no_animation=args.no_animation, verbose=args.verbose)
    if not ui.enhanced:
        parser.error("Open the preview in an interactive terminal with TERM other than dumb.")
    ui.notice("Preview only; no settings are read or changed.")
    ui.header("next preview")
    with ui.stage("Check setup"):
        time.sleep(1.5)
    root = "/Users/demo/.codex"
    plan = {
        "source": root + "/dsh-trace-extension/marketplace",
        "stateFile": root + "/dsh-trace-extension/setup.json",
        "traceRoot": root + "/rollout-traces",
        "customTraceRoot": False,
        "persistentLoginSetup": True,
        "changes": [],
        "commands": [],
    }
    if args.scenario != "unchanged":
        plan["changes"] = [{"action": "persist-bundled-plugin", "path": plan["source"]}]
        if args.scenario == "repair":
            plan["changes"].append(
                {
                    "action": "repair-owned-installed-files",
                    "path": root + "/plugins/cache/rollout-local/codex-dsh-trace/next",
                    "reason": "python-changed",
                    "missing": [],
                    "previousPython": "/usr/local/bin/python3",
                    "pythonExecutable": "/opt/conda/bin/python3",
                }
            )
        else:
            plan["changes"].extend(
                [
                    {"action": "set-login-environment", "value": plan["traceRoot"]},
                    {
                        "action": "write-login-launch-agent",
                        "path": "/Users/demo/Library/LaunchAgents/io.dsh-trace-extension.codex-recording.plist",
                    },
                ]
            )
        ui.summary(plan)
        ui.notice("Apply setup? [y/N/d=details] y  (simulated)", "[?_?]")
        try:
            with ui.stage("Set up Codex Trace"):
                time.sleep(1.6)
            with ui.stage("Verify plugin files"):
                time.sleep(1.1)
                if args.scenario == "error":
                    raise OSError("Synthetic error: the example plugin directory is read-only.")
        except OSError as exc:
            ui.notice(str(exc), "[!_!]")
        else:
            ui.result({"status": "configured", "pluginVersion": "next preview", "plan": plan})
    else:
        ui.result({"status": "unchanged", "pluginVersion": "next preview", "plan": plan})
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(
            json.dumps({"scenario": args.scenario, "events": stream.events}, ensure_ascii=False)
        )


if __name__ == "__main__":
    main()
