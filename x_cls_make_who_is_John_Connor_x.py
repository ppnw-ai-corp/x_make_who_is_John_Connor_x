"""JSON-in/JSON-out wrapper for the John Connor Copilot helper."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:  # pragma: no cover - executed when run as script
    sys.path.append(str(Path(__file__).resolve().parent))
    import who_is_jc  # type: ignore[import]  # noqa: E402
else:
    from . import who_is_jc


VALID_COPILOT_MODELS: tuple[str, ...] = (
    "gpt-5",
    "gpt-5.1",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex",
    "claude-sonnet-4.5",
    "claude-sonnet-4",
    "claude-haiku-4.5",
)

try:  # pragma: no cover - optional dependency
    from x_make_copilot_cli_one_time_setup_x import (  # type: ignore[import-not-found]
        x_cls_make_copilot_cli_one_time_setup_x,
    )
except ImportError:  # pragma: no cover - helper not available in all environments
    x_cls_make_copilot_cli_one_time_setup_x = None  # type: ignore[assignment]


def _bool_option(payload: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "y"}:
            return True
        if lowered in {"0", "false", "no", "off", "n"}:
            return False
    return default


@contextmanager
def _temporary_env(updates: Mapping[str, str | None]):
    previous: dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            elif value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class x_cls_make_who_is_John_Connor_x:  # noqa: N801 - legacy public API
    """Run the Copilot CLI helper using a JSON-friendly contract."""

    def __init__(self, ctx: object | None = None) -> None:
        self._ctx = ctx

    def run(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(request or {})
        question = str(payload.get("question") or who_is_jc.PROMPT)
        allow_http_fallback = payload.get("http_fallback")
        allow_token_prompt = payload.get("allow_token_prompt")
        language_raw = payload.get("language")
        model_raw = payload.get("model")
        model: str | None = None
        if model_raw is not None:
            if not isinstance(model_raw, str) or not model_raw.strip():
                return {
                    "status": "invalid_model",
                    "message": "Model must be a non-empty string when provided.",
                    "question": question,
                    "available_models": list(VALID_COPILOT_MODELS),
                }
            candidate = model_raw.strip()
            if candidate not in VALID_COPILOT_MODELS:
                return {
                    "status": "unsupported_model",
                    "message": f"Model '{candidate}' is not in the supported list.",
                    "question": question,
                    "available_models": list(VALID_COPILOT_MODELS),
                }
            model = candidate

        language: str | None = None
        if language_raw is not None:
            if not isinstance(language_raw, str) or not language_raw.strip():
                return {
                    "status": "invalid_language",
                    "message": "Language must be a non-empty string when provided.",
                    "question": question,
                }
            language = language_raw.strip()

        env_updates: dict[str, str | None] = {}
        if allow_http_fallback is not None:
            env_updates["COPILOT_HTTP_FALLBACK"] = "1" if _bool_option(payload, "http_fallback", True) else "0"
        if allow_token_prompt is not None:
            if _bool_option(payload, "allow_token_prompt", True):
                env_updates[who_is_jc._DISABLE_PROMPT_FLAG] = None  # noqa: SLF001 - module-level constant
            else:
                env_updates[who_is_jc._DISABLE_PROMPT_FLAG] = "1"  # noqa: SLF001

        attempt_setup = _bool_option(payload, "attempt_setup")
        setup_options_raw = payload.get("setup_options")
        setup_options = setup_options_raw if isinstance(setup_options_raw, Mapping) else {}

        with _temporary_env(env_updates):
            try:
                response = who_is_jc.query_copilot(question, model=model, language=language)
            except RuntimeError as exc:
                result: dict[str, Any] = {
                    "status": "error",
                    "question": question,
                    "message": str(exc),
                    "available_models": list(VALID_COPILOT_MODELS),
                    "options": {
                        "http_fallback": _bool_option(payload, "http_fallback", True)
                        if allow_http_fallback is not None
                        else None,
                        "allow_token_prompt": _bool_option(payload, "allow_token_prompt", True)
                        if allow_token_prompt is not None
                        else None,
                        "model": model,
                    },
                }
                if attempt_setup:
                    if x_cls_make_copilot_cli_one_time_setup_x is None:
                        result["setup"] = {
                            "status": "unavailable",
                            "message": "Copilot setup helper package is not installed.",
                        }
                    else:
                        setup_report = x_cls_make_copilot_cli_one_time_setup_x().run(setup_options)
                        result["setup"] = setup_report
                return result

        outcome = {
            "status": "ok",
            "question": response.get("question", question),
            "answer": response.get("answer", ""),
            "source": response.get("source"),
            "model": response.get("model"),
            "cli": response.get("cli"),
            "http": response.get("http"),
            "language": language,
            "available_models": list(VALID_COPILOT_MODELS),
            "options": {
                "http_fallback": _bool_option(payload, "http_fallback", True)
                if allow_http_fallback is not None
                else None,
                "allow_token_prompt": _bool_option(payload, "allow_token_prompt", True)
                if allow_token_prompt is not None
                else None,
                "model": model,
                "language": language,
            },
        }
        return outcome


def _load_request() -> Mapping[str, Any]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SystemExit(f"Invalid JSON input: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SystemExit("Input JSON must be an object.")
    return data


def main() -> int:
    request = _load_request()
    outcome = x_cls_make_who_is_John_Connor_x().run(request)
    print(json.dumps(outcome, indent=2))
    return 0 if outcome.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
