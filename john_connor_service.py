"""Persona vetting adapter for Who Is John Connor tooling."""

from __future__ import annotations

from typing import Any, Mapping

try:  # pragma: no cover - optional dependency until shared module installed
    from z_make_common_x.persona_vetting import (  # type: ignore[import-not-found]
        PersonaAuditTrail,
        PersonaVettingService,
    )
    from z_make_common_x.copilot_normalizer import (  # type: ignore[import-not-found]
        DEFAULT_PERSONA_PROMPT,
        PersonaPromptError,
        extract_answer_text,
        extract_highlights,
        extract_tags,
        format_persona_question,
        score_from_answer,
        source_from_response,
        synopsis_from_answer,
    )
except ImportError as exc:  # pragma: no cover - diagnostic aid
    raise ImportError(
        "z_make_common_x is required for JohnConnorPersonaService; install with "
        "'pip install -e ../z_make_common_x'"
    ) from exc

from . import who_is_jc


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
            self.raise_failure(persona_id, str(exc), cause=exc)
            raise
        response: Mapping[str, Any]
        try:
            response = who_is_jc.query_copilot(question, model=self._model, language=self._language)
        except RuntimeError as exc:  # pragma: no cover - passthrough
            self.raise_failure(persona_id, str(exc), cause=exc)
            raise  # satisfy type checkers; raise_failure always raises

        answer = extract_answer_text(response)
        audit = PersonaAuditTrail(
            dataset_version=response.get("model"),
            query_parameters={
                "model": self._model,
                "language": self._language,
            },
            raw_response=response,
        )
        score = score_from_answer(answer)
        synopsis = synopsis_from_answer(answer)
        tags = extract_tags(response)
        reasons = extract_highlights(response)
        return self.build_result(
            persona_id,
            score=score,
            source=source_from_response(response),
            display_name=response.get("question"),
            synopsis=synopsis,
            tags=tags,
            reasons=reasons,
            audit=audit,
        )
