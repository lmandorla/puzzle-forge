from forge.answers import answers_agree, tolerance_for
from forge.schema import AdversarialRecord, Answer, CodeRecord, ReasoningRecord, Rejection

CODE_FAILURE_REASONS = {
    "timeout": "code_timeout",
    "no_answer": "code_output_unparseable",
    "memory": "code_execution_error",
    "crash": "code_execution_error",
}


def decide(
    reasoning: ReasoningRecord,
    code: CodeRecord,
    adversarial: AdversarialRecord,
    answer_format: str,
    decimal_places: int | None,
) -> tuple[Answer | None, Rejection | None]:
    """Return (answer, None) for a valid puzzle or (None, rejection) for the graveyard."""
    if code.answer is None:
        last = code.attempts[-1].execution if code.attempts else None
        kind = last.error_kind if last else None
        return None, Rejection(
            stage="code_verifier",
            reason=CODE_FAILURE_REASONS.get(kind, "code_execution_error"),
            detail=f"program failed after {len(code.attempts)} attempt(s): {last.error if last else 'no attempts'}",
            reasoning_answer=reasoning.answer,
        )

    tolerance = tolerance_for(answer_format, decimal_places)
    if reasoning.answer is None or not answers_agree(reasoning.answer, code.answer, tolerance):
        return None, Rejection(
            stage="validity",
            reason="verifier_disagreement",
            detail=f"Fable's solution gives {reasoning.answer}, the program gives {code.answer}",
            reasoning_answer=reasoning.answer,
            code_answer=code.answer,
        )

    if adversarial.blocking:
        alternate = f" (alternate answer: {adversarial.alternate_answer})" if adversarial.alternate_answer is not None else ""
        return None, Rejection(
            stage="adversarial_verifier",
            reason="adversarial_ambiguity",
            detail=f"{adversarial.alternate_interpretation or adversarial.concerns}{alternate}",
            reasoning_answer=reasoning.answer,
            code_answer=code.answer,
        )

    return Answer(
        value=code.answer,
        format=answer_format,
        decimal_places=decimal_places if answer_format == "decimal" else None,
        tolerance=tolerance,
        expression=reasoning.answer_expression,
    ), None
