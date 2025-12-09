"""Persona vetting adapter for Who Is John Connor tooling."""

# mypy: ignore-errors

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from x_make_common_x import (
    DEFAULT_PERSONA_PROMPT,
    PersonaPromptError,
    PersonaVettingError,
    PersonaVettingService,
    extract_answer_text,
    extract_highlights,
    extract_tags,
    format_persona_question,
    score_from_answer,
    source_from_response,
    synopsis_from_answer,
)

from . import who_is_jc

if TYPE_CHECKING:
    from collections.abc import Mapping


class JohnConnorPersonaService(PersonaVettingService):
    """Vetting service that queries the Copilot-backed Who Is John Connor helper."""

    def __init__(
        self,
        *,
        question_template: str = DEFAULT_PERSONA_PROMPT,
        model: str | None = None,
        language: str | None = None,
    ) -> None:
        self._question_template = question_template
        self._model = model
        self._language = language

    def lookup(self, persona_id: str):
        try:
            question = format_persona_question(persona_id, self._question_template)
        except PersonaPromptError as exc:
            raise PersonaVettingError(str(exc)) from exc

        try:
            response_raw = who_is_jc.query_copilot(
                question, model=self._model, language=self._language,
            )
        except RuntimeError as exc:  # pragma: no cover - passthrough
            raise PersonaVettingError(str(exc)) from exc

        response = cast("Mapping[str, Any]", response_raw)
        answer = extract_answer_text(response)
        score = score_from_answer(answer)
        synopsis = synopsis_from_answer(answer)
        tags = extract_tags(response)
        reasons = extract_highlights(response)
        display_name = _optional_str(response.get("question")) or persona_id

        return self.build_result(
            persona_id,
            score=score,
            source=source_from_response(response),
            display_name=display_name,
            synopsis=synopsis,
            tags=tags,
            reasons=reasons,
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None
