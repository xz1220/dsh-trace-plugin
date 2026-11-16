#!/bin/sh
# Thin bootstrap for dsh-trace-extension. Keep this outer block: a truncated
# download must fail to parse before any setup or dependency checks can run.
{
  set -eu
  umask 077

  dsh_repository=${DSH_TRACE_REPOSITORY:-xz1220/dsh-trace-plugin}
  dsh_ref=${DSH_TRACE_REF:-main}
  dsh_selected_source=
  dsh_tmp=

  dsh_error() {
    printf '%s\n' "dsh-trace-extension: $*" >&2
    exit 1
  }

  dsh_usage() {
    cat <<'USAGE'
dsh-trace-extension installer (macOS / Codex)

Usage: sh install.sh [setup|doctor|uninstall] [options]

  --dry-run          Show the exact plan without changing configuration
  --yes              Apply without an interactive confirmation
  --json             Print machine-readable results
  --client codex     Agent to configure (currently Codex only)
  --source SOURCE    GitHub owner/repo or an existing marketplace checkout
  --ref REF          Git branch, tag, or commit for a downloaded setup helper
  --trace-root PATH  Recording directory (defaults under CODEX_HOME)
  --codex-home PATH  Codex configuration root
  --no-persist       Configure only the current macOS login session

Run doctor to inspect configuration; uninstall removes only managed resources.
Python 3.9+ and a compatible Codex CLI are required. No Node/npm build is needed.
This script never installs Python, quits Codex, or deletes your recordings.

Private GitHub downloads use an authenticated gh CLI. Public downloads can use
curl. DSH_TRACE_PYTHON selects a Python executable; DSH_TRACE_REF pins a ref.
USAGE
  }

  # Inspect bootstrap options while preserving the caller's argument boundaries.
  dsh_expect=
  for dsh_arg in "$@"; do
    if [ -n "$dsh_expect" ]; then
      case "$dsh_expect" in
        ref) dsh_ref=$dsh_arg ;;
        source) dsh_selected_source=$dsh_arg ;;
      esac
      dsh_expect=
      continue
    fi
    case "$dsh_arg" in
      -h|--help) dsh_usage; exit 0 ;;
      --ref) dsh_expect=ref ;;
      --ref=*) dsh_ref=${dsh_arg#--ref=} ;;
      --source) dsh_expect=source ;;
      --source=*) dsh_selected_source=${dsh_arg#--source=} ;;
    esac
  done
  [ -z "$dsh_expect" ] || dsh_error "--$dsh_expect requires a value."
  # A remote source override must resolve its own ref, not a commit from the
  # default repository. Existing local directories still use the trusted helper
  # selected by the invoked install.sh or by DSH_TRACE_REPOSITORY.
  case "$dsh_selected_source" in
    https://github.com/*)
      dsh_repository=${dsh_selected_source#https://github.com/}
      dsh_repository=${dsh_repository%.git}
      ;;
    git@github.com:*)
      dsh_repository=${dsh_selected_source#git@github.com:}
      dsh_repository=${dsh_repository%.git}
      ;;
    ''|/*|./*|../*|\~*) ;;
    */*)
      if [ ! -d "$dsh_selected_source" ]; then
        dsh_repository=$dsh_selected_source
      fi
      ;;
    *)
      [ -d "$dsh_selected_source" ] ||
        dsh_error 'A downloaded source must be a GitHub owner/repo or an existing local directory.'
      ;;
  esac
  case "$dsh_repository" in
    */*) ;;
    *) dsh_error 'DSH_TRACE_REPOSITORY must be a GitHub owner/repo.' ;;
  esac
  case "$dsh_repository" in
    *[!A-Za-z0-9_./-]*|/*|*/|*/*/*|*..*) dsh_error 'Invalid GitHub repository.' ;;
  esac
  case "$dsh_ref" in
    ''|-*|*[!A-Za-z0-9_./-]*) dsh_error 'REF must be a Git branch, tag, or commit.' ;;
  esac

  dsh_python=
  if [ -n "${DSH_TRACE_PYTHON:-}" ]; then
    dsh_python=$(command -v "$DSH_TRACE_PYTHON" 2>/dev/null) ||
      dsh_error 'DSH_TRACE_PYTHON does not name an executable.'
    "$dsh_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' ||
      dsh_error 'DSH_TRACE_PYTHON must be Python 3.9 or later.'
  else
    for dsh_candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
      dsh_found=$(command -v "$dsh_candidate" 2>/dev/null || true)
      [ -n "$dsh_found" ] || continue
      # Avoid triggering macOS's developer-tools installer from its Python stub.
      if [ "$dsh_found" = /usr/bin/python3 ] && [ "$(uname -s)" = Darwin ]; then
        xcode-select -p >/dev/null 2>&1 || continue
      fi
      if "$dsh_found" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        dsh_python=$dsh_found
        break
      fi
    done
  fi
  [ -n "$dsh_python" ] || dsh_error 'Python 3.9+ was not found. Install Python, then rerun this command; no configuration was changed.'

  dsh_helper=
  dsh_resolved_ref=
  # Only use a neighboring helper when this file itself was invoked by path.
  # A piped script must never pick executable code out of the current directory.
  case "$0" in
    */install.sh|install.sh)
      dsh_script_dir=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
      if [ -f "$dsh_script_dir/scripts/setup.py" ] && [ -f "$dsh_script_dir/.agents/plugins/marketplace.json" ]; then
        dsh_helper=$dsh_script_dir/scripts/setup.py
        [ -n "$dsh_selected_source" ] || dsh_selected_source=$dsh_script_dir
      fi
      ;;
  esac

  if [ -z "$dsh_helper" ]; then
    dsh_tmp=$(mktemp -d "${TMPDIR:-/tmp}/dsh-trace-installer.XXXXXX") ||
      dsh_error 'Could not create a private temporary directory.'
    dsh_cleanup() {
      [ -z "$dsh_tmp" ] || rm -rf -- "$dsh_tmp"
    }
    trap dsh_cleanup 0
    trap 'exit 130' INT
    trap 'exit 143' TERM

    dsh_get_json() {
      dsh_endpoint=$1
      dsh_destination=$2
      if command -v gh >/dev/null 2>&1; then
        if gh api "$dsh_endpoint" --hostname github.com >"$dsh_destination" 2>"$dsh_tmp/gh-error"; then
          return 0
        fi
      fi
      if command -v curl >/dev/null 2>&1; then
        if curl --fail --silent --show-error --location --max-time 30 --retry 2 \
          -H 'Accept: application/vnd.github+json' \
          "https://api.github.com/$dsh_endpoint" -o "$dsh_destination" 2>"$dsh_tmp/curl-error"; then
          return 0
        fi
      fi
      dsh_error 'Could not read the GitHub source. Private repositories require gh auth login and repository access; alternatively run install.sh from an authenticated checkout.'
    }

    dsh_encoded_ref=$("$dsh_python" -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$dsh_ref")
    dsh_get_json "repos/$dsh_repository/commits/$dsh_encoded_ref" "$dsh_tmp/commit.json"
    dsh_resolved_ref=$("$dsh_python" -c '
import json,re,sys
from pathlib import Path
p=Path(sys.argv[1]); raw=p.read_bytes()
if len(raw)>8*1024*1024: raise SystemExit("GitHub response is too large")
sha=json.loads(raw).get("sha", "")
if not re.fullmatch(r"[0-9a-f]{40}",sha): raise SystemExit("Invalid GitHub commit response")
print(sha)
' "$dsh_tmp/commit.json") || dsh_error 'Could not resolve the requested Git ref.'
    dsh_get_json "repos/$dsh_repository/contents/scripts/setup.py?ref=$dsh_resolved_ref" "$dsh_tmp/helper.json"
    dsh_helper=$dsh_tmp/setup.py
    "$dsh_python" -c '
import ast,base64,hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]); raw=p.read_bytes()
if len(raw)>8*1024*1024: raise SystemExit("GitHub response is too large")
item=json.loads(raw)
if item.get("type")!="file" or item.get("encoding")!="base64" or item.get("path")!="scripts/setup.py":
    raise SystemExit("Unexpected GitHub helper response")
data=base64.b64decode("".join(item.get("content", "").split()),validate=True)
if len(data)>2*1024*1024: raise SystemExit("Setup helper is too large")
blob=b"blob "+str(len(data)).encode()+b"\0"+data
if hashlib.sha1(blob).hexdigest()!=item.get("sha"):
    raise SystemExit("Setup helper failed Git blob verification")
ast.parse(data.decode("utf-8"))
Path(sys.argv[2]).write_bytes(data)
' "$dsh_tmp/helper.json" "$dsh_helper" || dsh_error 'The setup helper download failed validation; no configuration was changed.'
  fi

  [ -n "$dsh_selected_source" ] || dsh_selected_source=$dsh_repository
  if [ -n "$dsh_resolved_ref" ]; then
    "$dsh_python" "$dsh_helper" "$@" --source "$dsh_selected_source" --ref "$dsh_resolved_ref"
  else
    "$dsh_python" "$dsh_helper" "$@" --source "$dsh_selected_source"
  fi
}
