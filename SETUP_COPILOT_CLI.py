"""Minimal helper to guide the one-time GitHub Copilot CLI setup.

The `who_is_jc.py` helper depends on the GitHub Copilot CLI accepting a
fine-grained PAT (with the **Copilot Requests** permission). Although we
persist the token via the environment vault, the CLI still requires a
one-time `/login` handshake per machine. This script tries to smooth the
process by:

1. Resolving the PAT (prompting if it is not present in the environment).
2. Verifying that the Copilot CLI is installed.
3. Attempting a non-interactive probe to confirm the CLI sees the PAT.
4. If the probe fails, offering to launch an interactive Copilot session
    with the appropriate environment variables already set so you can run
    `/login` once manually.

After the handshake succeeds, re-run `who_is_jc.py` to verify that answers
flow without further prompts.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys

PAT_ENV_KEYS = (
    "COPILOT_REQUESTS_PAT",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)


def _resolve_pat() -> str | None:
    env = os.environ
    for key in PAT_ENV_KEYS:
        value = env.get(key)
        if value:
            return value.strip()
    return None


def _prompt_pat() -> str | None:
    print("Enter your fine-grained GitHub PAT (Copilot Requests). Input is hidden.")
    try:
        token = getpass.getpass("PAT: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("Aborted by user.")
        return None
    return token or None


def _ensure_copilot_cli() -> str | None:
    candidates = (
        "copilot",
        "copilot.exe",
        "github-copilot-cli",
        "github-copilot-cli.exe",
        "copilot.ps1",
    )
    for name in candidates:
        tool = shutil.which(name)
        if tool:
            return tool
    return None


def _build_env(pat: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in PAT_ENV_KEYS + (
        "COPILOT_REQUESTS_TOKEN",
        "COPILOT_TOKEN",
        "COPILOT_PAT",
        "COPILOT_GITHUB_TOKEN",
        "GITHUB_COPILOT_TOKEN",
        "GH_COPILOT_TOKEN",
    ):
        env[key] = pat
    env.setdefault("COPILOT_ALLOW_ALL", "1")
    env.setdefault("COPILOT_CLI_ALLOW_UNSAFE", "1")
    return env


def _run_probe(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell") or "powershell"
    command = (
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; "
        "copilot --prompt 'Copilot CLI setup probe' --allow-all-tools "
        "--stream off --no-color"
    )
    try:
        return subprocess.run(
            [powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or "Probe timed out (Copilot CLI likely awaits trust or /login)."
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=-999,
            stdout=stdout,
            stderr=stderr,
        )


def _launch_interactive(env: dict[str, str]) -> None:
    powershell = shutil.which("powershell") or "powershell"
    command = (
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; copilot"
    )
    print("Opening an interactive Copilot CLI session. Complete the following steps:")
    print("  1. When prompted, choose option 1 or 2 to trust the repository folder.")
    print("  2. Run the `/login` slash command.")
    print("  3. Paste the PAT when prompted, then wait for success confirmation.")
    print("  4. Exit the session with Ctrl+C when finished.\n")
    subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        env=env,
        check=False,
    )


def main() -> int:
    if os.name != "nt":
        print("This helper currently supports Windows PowerShell environments only.")
        return 1

    pat = _resolve_pat()
    if not pat:
        pat = _prompt_pat()
        if not pat:
            print("No PAT provided. Exiting.")
            return 1

    tool = _ensure_copilot_cli()
    if not tool:
        print("GitHub Copilot CLI not found on PATH. Install it with `npm install -g @github/copilot` and retry.")
        return 1

    env = _build_env(pat)
    print("Running a quick Copilot CLI probe...")
    probe = _run_probe(env)

    stdout = (probe.stdout or "").strip()
    stderr = (probe.stderr or "").strip()

    if probe.returncode == 0 and stdout:
        print("Copilot CLI accepted the PAT without additional steps.")
        print("You can now run who_is_jc.py.")
        return 0

    if probe.returncode == 0 and not stdout:
        print("Copilot CLI returned no output (likely still needs an interactive /login).")
    else:
        print("Copilot CLI reported an error during the probe:")
        if stderr:
            print(stderr)
        elif stdout:
            print(stdout)

    answer = input("Open an interactive Copilot CLI session now? [Y/n]: ").strip().lower()
    if answer in {"", "y", "yes"}:
        _launch_interactive(env)
        print("Re-run who_is_jc.py to verify the setup. If it still fails, run this helper again.")
        return 0

    print("Setup not completed. Run `copilot`, execute /login, then rerun who_is_jc.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
