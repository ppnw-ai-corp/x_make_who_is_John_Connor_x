"""Throwaway helper to ask GitHub Copilot CLI who John Connor is."""

# mypy: ignore-errors

from __future__ import annotations

import contextlib
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

try:
    import winreg  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - non-Windows platforms
    winreg = None  # type: ignore[assignment]

PROMPT = "Who is John Connor?"
_TOKEN_CACHE: str | None = None
_TOKEN_ENV_KEYS = (
    "COPILOT_REQUESTS_PAT",
    "COPILOT_REQUESTS_TOKEN",
    "COPILOT_PAT",
    "COPILOT_TOKEN",
    "COPILOT_GITHUB_TOKEN",
    "GITHUB_COPILOT_TOKEN",
    "GH_COPILOT_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)
_TOKEN_EXPORT_KEYS = (
    "COPILOT_REQUESTS_PAT",
    "COPILOT_REQUESTS_TOKEN",
    "COPILOT_PAT",
    "COPILOT_TOKEN",
    "COPILOT_GITHUB_TOKEN",
    "GITHUB_COPILOT_TOKEN",
    "GH_COPILOT_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)
_DISABLE_PROMPT_FLAG = "WHO_IS_JC_DISABLE_TOKEN_PROMPT"
_SETUP_HELPER_PATH = Path(__file__).with_name("SETUP_COPILOT_CLI.py")
_SETUP_HELPER_ATTEMPTED = False


def _read_user_environment_variable(name: str) -> str | None:
    if os.name != "nt" or winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:  # type: ignore[attr-defined]
            value, _value_type = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if isinstance(value, str):
        return value
    return None


def _failure(code: int, message: str) -> tuple[int, str, str]:
    return code, "", f"{message}\n"


def _query_copilot_http(
    question: str, token: str, *, model: str | None = None,
) -> tuple[str, dict[str, object]]:
    endpoint = os.environ.get(
        "COPILOT_API_URL",
        "https://copilot-proxy.githubusercontent.com/v1/chat/completions",
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "who_is_jc/1.0",
        "Editor-Version": "who_is_jc/1.0",
        "OpenAI-Intent": "conversation-panel",
    }
    payload = {
        "model": model or os.environ.get("COPILOT_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are GitHub Copilot answering a single user prompt without requiring "
                    "additional interaction. Provide concise, direct responses."
                ),
            },
            {"role": "user", "content": question},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )  # noqa: S310 - endpoint is user-configurable but constrained via env
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            raw_bytes = response.read()
            body = raw_bytes.decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else exc.reason
        msg = f"Copilot HTTP request failed ({exc.code}): {detail}"
        raise RuntimeError(msg) from exc
    except (
        urllib.error.URLError
    ) as exc:  # pragma: no cover - network failures vary by environment
        msg = f"Copilot HTTP request failed: {exc.reason}"
        raise RuntimeError(msg) from exc

    try:
        payload_obj = json.loads(body)
    except json.JSONDecodeError as exc:
        msg = f"Copilot HTTP response was not valid JSON: {exc}"
        raise RuntimeError(msg)

    choices = payload_obj.get("choices")
    if not isinstance(choices, list) or not choices:
        msg = "Copilot HTTP response did not contain choices"
        raise RuntimeError(msg)
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        msg = "Copilot HTTP response missing message content"
        raise TypeError(msg)
    content = message.get("content")
    if not isinstance(content, str):
        msg = "Copilot HTTP response did not include text content"
        raise TypeError(msg)
    return content.strip(), payload


def _path_variants(executable_names: list[str]) -> list[Path]:
    candidates: list[Path] = []
    program_files_raw = os.environ.get("PROGRAMFILES") or r"C:\\Program Files"
    program_files = Path(program_files_raw)
    local_app_data_raw = os.environ.get("LOCALAPPDATA") or ""
    local_app_data = Path(local_app_data_raw) if local_app_data_raw else None

    for name in executable_names:
        exe_name = Path(name)
        candidates.extend(
            [
                program_files / "GitHub" / "Copilot" / exe_name,
                program_files / "GitHub Copilot" / exe_name,
            ],
        )
        if local_app_data:
            candidates.extend(
                [
                    local_app_data / "Programs" / "GitHub" / "Copilot" / exe_name,
                    local_app_data / "Programs" / exe_name,
                ],
            )

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for directory in path_dirs:
        if not directory:
            continue
        base = Path(directory)
        candidates.extend(base / name for name in executable_names)
    return candidates


def _find_winget() -> str | None:
    system_root = Path(os.environ.get("SYSTEMROOT") or r"C:\\Windows")
    winget_path = system_root / "System32" / "winget.exe"
    if winget_path.exists():
        return str(winget_path)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe"
        if candidate.exists():
            return str(candidate)
    return None


def _find_copilot_cli_executable() -> str | None:
    names = [
        "github-copilot-cli.exe",
        "github-copilot-cli.cmd",
        "github-copilot-cli.ps1",
        "github-copilot-cli",
        "copilot.exe",
        "copilot.cmd",
        "copilot.ps1",
        "copilot",
    ]
    for candidate in _path_variants(names):
        if candidate.exists():
            return str(candidate)
    return None


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _install_gh_cli() -> bool:
    if _install_gh_cli_via_winget():
        return True

    return _install_gh_cli_via_msi()


def _install_copilot_cli() -> bool:
    if _install_copilot_cli_via_winget():
        return True
    if _install_copilot_cli_via_npm():
        return True
    sys.stderr.write(
        "Unable to install the GitHub Copilot CLI automatically. Install it manually from "
        "https://github.com/github/copilot-cli and retry.\n",
    )
    return False


def _install_copilot_cli_via_winget() -> bool:
    winget = _find_winget()
    if winget is None:
        return False
    sys.stderr.write("Attempting to install GitHub Copilot CLI via winget...\n")
    try:
        attempt = subprocess.run(  # noqa: S603 - invokes system installer with fixed args
            [
                winget,
                "install",
                "GitHub.CopilotCLI",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("winget install for Copilot CLI timed out.\n")
        return False
    if attempt.returncode != 0:
        sys.stderr.write(
            f"winget failed to install GitHub Copilot CLI (exit code {attempt.returncode}).\n",
        )
        return False
    sys.stderr.write("GitHub Copilot CLI installed.\n")
    return True


def _install_gh_cli_via_winget() -> bool:
    winget = _find_winget()
    if winget is None:
        return False

    sys.stderr.write("Attempting to install GitHub CLI via winget...\n")
    try:
        attempt = subprocess.run(  # noqa: S603 - invokes winget with trusted arguments
            [
                winget,
                "install",
                "GitHub.cli",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("winget install timed out; falling back to manual download.\n")
        return False

    if attempt.returncode != 0:
        sys.stderr.write(
            f"winget failed with exit code {attempt.returncode}; falling back to manual download.\n",
        )
        return False
    sys.stderr.write("GitHub CLI installed.\n")
    return True


def _find_npm() -> str | None:
    npm = shutil.which("npm")
    if npm:
        return npm
    npm_cmd = shutil.which("npm.cmd")
    if npm_cmd:
        return npm_cmd
    return None


def _install_copilot_cli_via_npm() -> bool:
    npm = _find_npm()
    if npm is None:
        sys.stderr.write(
            "npm was not found on PATH. Install Node.js 22 or later (which bundles npm 10+) and retry.\n",
        )
        return False

    sys.stderr.write("Attempting to install GitHub Copilot CLI via npm...\n")
    command: list[str] | str
    if npm.lower().endswith((".cmd", ".bat")):
        command = f'"{npm}" install -g @github/copilot'
        runner = [os.environ.get("COMSPEC", "cmd.exe"), "/c", command]
    else:
        runner = [npm, "install", "-g", "@github/copilot"]
    try:
        attempt = subprocess.run(  # noqa: S603 - npm invocation uses trusted package
            runner,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("npm install for Copilot CLI timed out.\n")
        return False

    if attempt.returncode != 0:
        sys.stderr.write(
            f"npm failed to install GitHub Copilot CLI (exit code {attempt.returncode}).\n",
        )
        return False

    sys.stderr.write("GitHub Copilot CLI installed via npm.\n")
    return True


def _install_gh_cli_via_msi() -> bool:
    version = "2.83.0"
    url = (
        "https://github.com/cli/cli/releases/download/"
        f"v{version}/gh_{version}_windows_amd64.msi"
    )
    sys.stderr.write("Attempting direct GitHub CLI download...\n")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".msi", delete=False) as handle:
            tmp_path = Path(handle.name)
        urllib.request.urlretrieve(url, str(tmp_path))  # noqa: S310 - trusted release URL
        sys.stderr.write("Download complete. Installing...\n")
        system_root = Path(os.environ.get("SYSTEMROOT") or r"C:\\Windows")
        msiexec = system_root / "System32" / "msiexec.exe"
        install = subprocess.run(  # noqa: S603 - MSI install uses fixed arguments
            [
                str(msiexec),
                "/i",
                str(tmp_path),
                "/qn",
                "/norestart",
                "ALLUSERS=0",
            ],
            check=False,
        )
        if install.returncode != 0:
            sys.stderr.write(
                f"MSI installation failed with exit code {install.returncode}. Install GitHub CLI manually from "
                "https://cli.github.com/.\n",
            )
            return False
        sys.stderr.write("GitHub CLI installed via MSI.\n")
        return True
    except Exception as exc:  # noqa: BLE001 - keep turnkey
        sys.stderr.write(
            f"Failed to download/install GitHub CLI automatically: {exc}\n",
        )
        sys.stderr.write("Install manually from https://cli.github.com/ and retry.\n")
        return False
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)


def _find_gh_executable() -> str | None:
    gh_candidates: list[Path] = []
    program_files = os.environ.get("PROGRAMFILES") or r"C:\\Program Files"
    gh_candidates.append(Path(program_files) / "GitHub CLI" / "gh.exe")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        gh_candidates.append(Path(local_app_data) / "Programs" / "GitHub CLI" / "gh.exe")
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    gh_candidates.extend(Path(d) / "gh.exe" for d in path_dirs if d)

    for candidate in gh_candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _token_prompt_allowed() -> bool:
    raw = os.environ.get(_DISABLE_PROMPT_FLAG)
    if raw is None:
        return True
    lowered = raw.strip().lower()
    return lowered not in {"1", "true", "yes", "on", "y"}


def _resolve_token() -> str | None:
    env = os.environ
    direct = env.get("COPILOT_REQUESTS_PAT")
    if direct:
        return direct.strip()
    if os.name == "nt":
        persisted = _read_user_environment_variable("COPILOT_REQUESTS_PAT")
        if persisted:
            return persisted.strip()
    for key in _TOKEN_ENV_KEYS[1:]:
        value = env.get(key)
        if value:
            return value.strip()
    if os.name == "nt":
        for key in _TOKEN_ENV_KEYS:
            value = _read_user_environment_variable(key)
            if value:
                return value.strip()
    global _TOKEN_CACHE
    return _TOKEN_CACHE


def _copilot_env(prompt: bool = False) -> dict[str, str]:
    env = dict(os.environ)
    global _TOKEN_CACHE
    token = _resolve_token()
    if prompt and token is None and _token_prompt_allowed():
        new_token = _prompt_for_token()
        if new_token:
            _TOKEN_CACHE = new_token
            token = new_token
    if token:
        for key in _TOKEN_EXPORT_KEYS:
            if key in {"GITHUB_TOKEN", "GH_TOKEN"} and env.get(key):
                continue
            env[key] = token
    return env


def _prompt_for_token() -> str | None:
    message = (
        "GitHub Copilot CLI can use a Fine-grained Personal Access Token with the 'Copilot Requests' "
        "permission. Generate one at https://github.com/settings/personal-access-tokens/new.\n"
        "Paste the token below to continue (input hidden). Press Enter to skip.\n"
    )
    sys.stderr.write("Copilot authentication required.\n")
    sys.stderr.write(message)
    try:
        token = getpass.getpass("Copilot token: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("Skipping token prompt.\n")
        return None
    if not token:
        return None

    persist_answer = (
        input("Persist token via `setx GH_TOKEN` for future runs? [y/N]: ")
        .strip()
        .lower()
    )
    if persist_answer in {"y", "yes"}:
        _persist_token(token)
    return token


def _persist_token(token: str) -> None:
    setx = shutil.which("setx")
    if setx is None:
        sys.stderr.write("setx.exe not found; unable to persist token automatically.\n")
        return
    targets = ("COPILOT_REQUESTS_PAT", "GH_TOKEN", "GITHUB_TOKEN")
    last_variable = None
    try:
        for variable in targets:
            last_variable = variable
            subprocess.run(
                [setx, variable, token],
                check=True,
                capture_output=True,
                text=True,
            )
        sys.stderr.write(
            "Token persisted to COPILOT_REQUESTS_PAT, GH_TOKEN, and GITHUB_TOKEN. Restart terminals to pick up the new values.\n",
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"Failed to persist token (exit code {exc.returncode}) while writing {last_variable}. "
            "You can run `setx <name> <token>` manually.\n",
        )


def _invoke_setup_helper() -> bool:
    """Run the setup helper once and report whether Copilot should be retried."""

    global _SETUP_HELPER_ATTEMPTED
    if _SETUP_HELPER_ATTEMPTED:
        return False
    _SETUP_HELPER_ATTEMPTED = True

    if not _SETUP_HELPER_PATH.exists():
        sys.stderr.write(
            "Setup helper SETUP_COPILOT_CLI.py was not found; skipping automatic onboarding.\n",
        )
        return False

    python_exe = sys.executable or "python"
    sys.stderr.write("Launching Copilot CLI setup helper...\n")
    try:
        result = subprocess.run(
            [python_exe, str(_SETUP_HELPER_PATH)],
            env=_copilot_env(),
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - surface unexpected failures
        sys.stderr.write(f"Failed to launch Copilot setup helper: {exc}\n")
        return False

    if result.returncode == 0:
        sys.stderr.write("Setup helper completed. Retrying Copilot CLI call...\n")
        return True

    sys.stderr.write(
        f"Copilot setup helper exited with status {result.returncode}. Resolve the issue and rerun who_is_jc.\n",
    )
    return False


def _is_auth_error(output: str) -> bool:
    lowered = output.lower()
    indicators = (
        "no authentication information",
        "/login",
        "authenticate with github",
        "copilot can be authenticated",
        "start 'copilot' and run the '/login'",
    )
    return any(indicator in lowered for indicator in indicators)


def _run_copilot_cli(prompt: str, *, model: str | None = None) -> tuple[int, str, str]:
    exe = _find_copilot_cli_executable()
    if exe is None:
        if not _install_copilot_cli():
            return _failure(
                128,
                "Unable to install the GitHub Copilot CLI automatically. Install it manually and retry.",
            )
        exe = _find_copilot_cli_executable()
        if exe is None:
            return _failure(
                128,
                "GitHub Copilot CLI installation did not expose the executable. Install manually and retry.",
            )

    prompt_payload = f"ask {prompt}" if not prompt.lower().startswith("ask") else prompt
    powershell = shutil.which("powershell") or "powershell"

    exe_literal = _ps_quote(exe)
    prompt_literal = _ps_quote(prompt_payload)
    command_parts = [
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; ",
        f"& {exe_literal} --prompt {prompt_literal} --allow-all-tools --stream off --no-color",
    ]
    if model:
        command_parts.append(f" --model { _ps_quote(model) }")
    command_text = "".join(command_parts)

    def execute(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [powershell, "-NoProfile", "-Command", command_text],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    attempted_prompt = False
    next_prompt = False

    while True:
        env = _copilot_env(prompt=True) if next_prompt else dict(os.environ)
        next_prompt = False
        if model:
            env["COPILOT_MODEL"] = model
        result = execute(env)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = stdout + stderr
        auth_error = _is_auth_error(combined)
        if result.returncode == 0 and not auth_error:
            return 0, stdout, stderr

        token_available = _resolve_token() is not None
        if (
            auth_error
            and not token_available
            and not attempted_prompt
            and _token_prompt_allowed()
        ):
            attempted_prompt = True
            next_prompt = True
            continue

        if auth_error:
            if _invoke_setup_helper():
                next_prompt = False
                continue
            tip = (
                "Tip: launch `copilot` interactively, run the `/login` command, or persist a Copilot Requests PAT "
                "via `set_persistent_env_var` (e.g., store it as COPILOT_REQUESTS_PAT then rerun).\n"
            )
            stderr = f"{stderr}{tip}" if stderr else tip
            if result.returncode == 0:
                return 1, stdout, stderr
            return result.returncode, stdout, stderr

        return result.returncode, stdout, stderr


def _copilot_command_available(gh_exe: str) -> bool:
    probe = subprocess.run(
        [gh_exe, "copilot", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=_copilot_env(),
    )
    return probe.returncode == 0


def _ensure_copilot_extension(gh_exe: str) -> bool:
    if _copilot_command_available(gh_exe):
        return True

    sys.stderr.write("Installing GitHub Copilot CLI extension...\n")
    install = subprocess.run(
        [gh_exe, "extension", "install", "github/gh-copilot", "--force"],
        env=_copilot_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if install.returncode != 0:
        sys.stderr.write(install.stderr or install.stdout or "")
        sys.stderr.write(
            "Failed to install the GitHub Copilot extension. You can install it manually with "
            "`gh extension install github/gh-copilot`.\n",
        )
        return False
    if _copilot_command_available(gh_exe):
        return True
    sys.stderr.write(
        "GitHub Copilot CLI extension did not register the `gh copilot` command. Install manually and retry.\n",
    )
    return False


def _ensure_gh_auth(gh_exe: str) -> bool:
    status = subprocess.run(
        [gh_exe, "auth", "status"],
        env=_copilot_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode == 0:
        return True

    sys.stderr.write(status.stderr or status.stdout or "")
    sys.stderr.write(
        "GitHub CLI is not authenticated. Run `gh auth login` (use the account with Copilot access) and retry.\n",
    )
    return False


def run_copilot_query(prompt: str, *, model: str | None = None) -> tuple[int, str, str]:
    """Invoke Copilot CLI flows and return (exit_code, stdout, stderr)."""

    code, stdout, stderr = _run_copilot_cli(prompt, model=model)
    if code == 0 or code not in (128, 127):
        return code, stdout, stderr

    gh_exe = _find_gh_executable()
    if gh_exe is None:
        if not _install_gh_cli():
            return _failure(
                127,
                "GitHub CLI is not installed. Install it from https://cli.github.com/ and retry.",
            )
        gh_exe = _find_gh_executable()
        if gh_exe is None:
            return _failure(
                127,
                "GitHub CLI install did not yield gh.exe. Install manually and retry.",
            )

    if not _ensure_copilot_extension(gh_exe):
        return _failure(127, "GitHub Copilot CLI extension is unavailable.")

    if not _ensure_gh_auth(gh_exe):
        return _failure(
            127, "GitHub CLI authentication is required. Run `gh auth login` and retry.",
        )

    result = subprocess.run(
        [gh_exe, "copilot", "suggest", prompt],
        env=_copilot_env(),
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout or "", result.stderr or ""


def query_copilot(
    question: str = PROMPT,
    *,
    model: str | None = None,
    language: str | None = None,
) -> dict[str, object]:
    """Return a dictionary containing the question, answer, and diagnostics."""

    effective_question = _apply_language_directive(question, language)
    code, stdout, stderr = run_copilot_query(effective_question, model=model)
    answer = stdout.strip()
    message = stderr.strip() if stderr else ""
    model_effective = model or os.environ.get("COPILOT_MODEL") or "default"
    cli_report: dict[str, object] = {
        "returncode": code,
        "stdout": stdout,
        "stderr": stderr,
        "model": model_effective,
        "language": language,
    }

    if code == 0 and answer:
        return {
            "question": question,
            "answer": answer,
            "source": "cli",
            "model": model_effective,
            "cli": cli_report,
            "language": language,
        }

    if code != 0:
        detail = message or stdout.strip() or f"Copilot CLI exited with status {code}"
        raise RuntimeError(detail)

    token = _resolve_token()
    fallback_raw = os.environ.get("COPILOT_HTTP_FALLBACK")
    fallback_allowed = True if fallback_raw is None else fallback_raw.strip().lower() in {"1", "true", "yes", "on", "y"}
    if token and fallback_allowed:
        try:
            http_answer, http_payload = _query_copilot_http(
                effective_question, token, model=model,
            )
        except Exception as exc:  # noqa: BLE001 - fallback path
            if not message:
                message = str(exc)
        else:
            if http_answer:
                return {
                    "question": question,
                    "answer": http_answer,
                    "source": "http",
                    "model": http_payload.get("model", model_effective),
                    "cli": cli_report,
                    "http": {
                        "request": http_payload,
                    },
                    "language": language,
                }
    detail = (
        message
        or "Copilot returned an empty response. Run `copilot` interactively and complete `/login` once to authorize this PAT."
    )
    raise RuntimeError(detail)


def main() -> None:
    args = sys.argv[1:]
    question = " ".join(args).strip() if args else ""
    question = question or PROMPT
    try:
        result = query_copilot(question)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
    output = {"question": result["question"], "answer": result["answer"]}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()


def _apply_language_directive(question: str, language: str | None) -> str:
    if not language:
        return question
    lang = language.strip().lower()
    if lang.startswith("es"):
        return (
            question
            + "\n\nResponde en español latino, claro, cálido y con empatía. Si el contenido incluye nombres propios en otro idioma, consérvalos."
        )
    if lang.startswith("en"):
        return (
            question
            + "\n\nPlease answer in clear, friendly English suitable for all ages."
        )
    return question + f"\n\nPlease answer in {language} with warmth and clarity."
