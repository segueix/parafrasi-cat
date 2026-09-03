"""Resultats de la canonada, amb tota la informació necessària per explicar-los."""

from __future__ import annotations

import json
from dataclasses import dataclass

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.validation.result import ValidationResult


@dataclass(frozen=True, slots=True)
class EvaluatedCandidate:
    """Un candidat amb el resultat de validació i, si l'ha superada, la puntuació."""

    candidate: Candidate
    validation: ValidationResult
    score: ScoreBreakdown | None
    selected: bool = False

    @property
    def accepted(self) -> bool:
        return self.validation.ok and self.score is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "validation": self.validation.to_dict(),
            "score": None if self.score is None else self.score.to_dict(),
            "selected": self.selected,
        }


@dataclass(frozen=True, slots=True)
class RejectedProposal:
    """Transformació proposada per una regla i descartada abans de generar candidats."""

    transformation: Transformation
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"transformation": self.transformation.to_dict(), "reason": self.reason}


@dataclass(frozen=True, slots=True)
class SentenceResult:
    """Resultat del processament d'una frase."""

    index: int
    source_text: str
    span: Span
    output_text: str
    candidates: tuple[EvaluatedCandidate, ...]
    rejected_proposals: tuple[RejectedProposal, ...]
    protected_spans: tuple[ProtectedSpan, ...]

    @property
    def selected(self) -> EvaluatedCandidate:
        for evaluated in self.candidates:
            if evaluated.selected:
                return evaluated
        raise LookupError("Cap candidat seleccionat")  # pragma: no cover

    @property
    def transformations(self) -> tuple[Transformation, ...]:
        return self.selected.candidate.transformations

    @property
    def changed(self) -> bool:
        return self.output_text != self.source_text

    @property
    def alternatives(self) -> tuple[str, ...]:
        """Textos de tots els candidats acceptats (validats), sense l'identitat."""
        return tuple(
            e.candidate.text for e in self.candidates if e.accepted and not e.candidate.is_identity
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source_text": self.source_text,
            "span": self.span.to_dict(),
            "output_text": self.output_text,
            "changed": self.changed,
            "transformations": [t.to_dict() for t in self.transformations],
            "alternatives": list(self.alternatives),
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected_proposals": [r.to_dict() for r in self.rejected_proposals],
            "protected_spans": [p.to_dict() for p in self.protected_spans],
        }


@dataclass(frozen=True, slots=True)
class ParagraphResult:
    """Resultat de les regles de paràgraf (fusió de frases) sobre un paràgraf.

    ``intermediate_text`` és el paràgraf després de les transformacions de
    frase; ``output_text`` el resultat final del paràgraf.
    """

    index: int
    source_text: str
    intermediate_text: str
    span: Span
    output_text: str
    candidates: tuple[EvaluatedCandidate, ...]
    rejected_proposals: tuple[RejectedProposal, ...]
    protected_spans: tuple[ProtectedSpan, ...]

    @property
    def selected(self) -> EvaluatedCandidate:
        for evaluated in self.candidates:
            if evaluated.selected:
                return evaluated
        raise LookupError("Cap candidat seleccionat")  # pragma: no cover

    @property
    def transformations(self) -> tuple[Transformation, ...]:
        return self.selected.candidate.transformations

    @property
    def changed(self) -> bool:
        return self.output_text != self.intermediate_text

    @property
    def alternatives(self) -> tuple[str, ...]:
        return tuple(
            e.candidate.text for e in self.candidates if e.accepted and not e.candidate.is_identity
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source_text": self.source_text,
            "intermediate_text": self.intermediate_text,
            "span": self.span.to_dict(),
            "output_text": self.output_text,
            "changed": self.changed,
            "transformations": [t.to_dict() for t in self.transformations],
            "alternatives": list(self.alternatives),
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected_proposals": [r.to_dict() for r in self.rejected_proposals],
        }


@dataclass(frozen=True, slots=True)
class ParaphraseResult:
    """Resultat complet d'una execució de la canonada."""

    source_text: str
    output_text: str
    sentences: tuple[SentenceResult, ...]
    protected_spans: tuple[ProtectedSpan, ...]
    rule_set_name: str = ""
    rule_ids: tuple[str, ...] = ()
    style_profile_name: str = ""
    paragraphs: tuple[ParagraphResult, ...] = ()

    @property
    def transformations(self) -> tuple[Transformation, ...]:
        sentence_level = tuple(t for s in self.sentences for t in s.transformations)
        paragraph_level = tuple(t for p in self.paragraphs for t in p.transformations)
        return sentence_level + paragraph_level

    @property
    def changed(self) -> bool:
        return self.output_text != self.source_text

    @property
    def n_candidates(self) -> int:
        return sum(len(s.candidates) for s in self.sentences) + sum(
            len(p.candidates) for p in self.paragraphs
        )

    @property
    def n_rejected_candidates(self) -> int:
        return sum(1 for s in self.sentences for c in s.candidates if not c.accepted) + sum(
            1 for p in self.paragraphs for c in p.candidates if not c.accepted
        )

    def alternatives(self, sentence_index: int) -> tuple[str, ...]:
        """Variants acceptades d'una frase (drecera per a ``sentences[i].alternatives``)."""
        return self.sentences[sentence_index].alternatives

    def explain(self) -> str:
        """Informe llegible en català de tot el que ha passat."""
        lines: list[str] = []
        lines.append("=== Informe de reredacció ===")
        lines.append(f"Conjunt de regles: {self.rule_set_name or '(cap)'}")
        lines.append("Regles actives: " + (", ".join(self.rule_ids) if self.rule_ids else "cap"))
        if self.style_profile_name:
            lines.append(f"Perfil d'estil: {self.style_profile_name}")
        lines.append(
            f"Frases: {len(self.sentences)} · Transformacions aplicades: "
            f"{len(self.transformations)} · Candidats avaluats: {self.n_candidates} · "
            f"Candidats rebutjats per validació: {self.n_rejected_candidates}"
        )
        lines.append("")
        lines.append(f"Fragments protegits ({len(self.protected_spans)}):")
        if self.protected_spans:
            lines.extend(f"  - {p.describe()}" for p in self.protected_spans)
        else:
            lines.append("  (cap)")
        for sentence in self.sentences:
            lines.append("")
            lines.append(f"Frase {sentence.index + 1}: «{sentence.source_text}»")
            _explain_unit(lines, sentence.source_text, sentence.output_text, sentence.candidates)
            for rejected in sentence.rejected_proposals:
                described = rejected.transformation.describe()
                lines.append(f"  ✘ Proposta descartada {described} — {rejected.reason}")
        for paragraph in self.paragraphs:
            if len(paragraph.candidates) <= 1 and not paragraph.rejected_proposals:
                continue
            lines.append("")
            lines.append(f"Paràgraf {paragraph.index + 1} (regles entre frases):")
            _explain_unit(
                lines, paragraph.intermediate_text, paragraph.output_text, paragraph.candidates
            )
            for rejected in paragraph.rejected_proposals:
                described = rejected.transformation.describe()
                lines.append(f"  ✘ Proposta descartada {described} — {rejected.reason}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_text": self.source_text,
            "output_text": self.output_text,
            "changed": self.changed,
            "rule_set": self.rule_set_name,
            "rule_ids": list(self.rule_ids),
            "style_profile": self.style_profile_name,
            "transformations": [t.to_dict() for t in self.transformations],
            "protected_spans": [p.to_dict() for p in self.protected_spans],
            "sentences": [s.to_dict() for s in self.sentences],
            "paragraphs": [p.to_dict() for p in self.paragraphs],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _explain_unit(
    lines: list[str],
    source_text: str,
    output_text: str,
    candidates: tuple[EvaluatedCandidate, ...],
) -> None:
    selected = next((c for c in candidates if c.selected), None)
    if output_text != source_text and selected is not None:
        lines.append(f"  → «{output_text}»")
        lines.extend(f"  ✔ {t.describe()}" for t in selected.candidate.transformations)
    else:
        lines.append("  → sense canvis")
    for evaluated in candidates:
        if evaluated.selected or evaluated.candidate.is_identity:
            continue
        if evaluated.score is None:
            reasons = "; ".join(i.describe() for i in evaluated.validation.errors)
            lines.append(f"  ✘ Candidat rebutjat «{evaluated.candidate.text}»: {reasons}")
        else:
            rules = ", ".join(evaluated.candidate.rule_ids)
            lines.append(
                f"  · Candidat no seleccionat «{evaluated.candidate.text}» "
                f"[{rules}] (puntuació {evaluated.score.total:+.3f}: {evaluated.score.explanation})"
            )
