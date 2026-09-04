"""Resultats de la canonada, amb tota la informació necessària per explicar-los."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.scoring.scorer import ScoreBreakdown
from parafrasi_cat.validation.result import ValidationResult


@dataclass(frozen=True, slots=True)
class EvaluatedCandidate:
    """Un candidat amb el resultat de validació i la puntuació."""

    candidate: Candidate
    validation: ValidationResult
    score: ScoreBreakdown | None
    selected: bool = False

    @property
    def accepted(self) -> bool:
        """Cert si ha superat la validació i cap dimensió de preservació l'invalida."""
        return self.validation.ok and self.score is not None and self.score.valid

    @property
    def rejection_reason(self) -> str:
        """Motiu del descart (buit si el candidat és acceptable)."""
        if not self.validation.ok:
            return self.validation.summary
        if self.score is not None and not self.score.valid:
            return "; ".join(self.score.invalidating)
        return ""

    @property
    def importance(self) -> float:
        """Importància d'un candidat descartat: confiança acumulada de les transformacions."""
        return sum(t.confidence for t in self.candidate.transformations)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "validation": self.validation.to_dict(),
            "score": None if self.score is None else self.score.to_dict(),
            "selected": self.selected,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class RejectedProposal:
    """Transformació proposada per una regla i descartada abans de generar candidats."""

    transformation: Transformation
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"transformation": self.transformation.to_dict(), "reason": self.reason}


@dataclass(frozen=True, slots=True)
class DiscardedCandidate:
    """Un candidat no escollit i el motiu."""

    evaluated: EvaluatedCandidate
    reason: str

    @property
    def text(self) -> str:
        return self.evaluated.candidate.text

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "rule_ids": list(self.evaluated.candidate.rule_ids),
            "accepted": self.evaluated.accepted,
            "score": None if self.evaluated.score is None else self.evaluated.score.total,
            "reason": self.reason,
        }


class _UnitResult:
    """Comportament comú dels resultats de frase i de paràgraf."""

    candidates: tuple[EvaluatedCandidate, ...]
    rejected_proposals: tuple[RejectedProposal, ...]
    notes: tuple[str, ...]
    """Explicacions del motor sobre el que no ha transformat, i per què."""

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
    def alternatives(self) -> tuple[str, ...]:
        """Textos de tots els candidats acceptats (validats), sense l'identitat."""
        return tuple(
            e.candidate.text for e in self.candidates if e.accepted and not e.candidate.is_identity
        )

    @property
    def applied_rule_ids(self) -> tuple[str, ...]:
        return self.selected.candidate.rule_ids

    def discarded(self, limit: int = 5) -> tuple[DiscardedCandidate, ...]:
        """Candidats no escollits més importants, amb el motiu del descart.

        Primer els acceptats però no seleccionats (per puntuació), després els
        rebutjats per la validació o la puntuació (per importància).
        """
        best_total = self.selected.score.total if self.selected.score is not None else 0.0
        accepted: list[DiscardedCandidate] = []
        rejected: list[DiscardedCandidate] = []
        for evaluated in self.candidates:
            if evaluated.selected or evaluated.candidate.is_identity:
                continue
            if evaluated.accepted:
                total = evaluated.score.total if evaluated.score is not None else 0.0
                accepted.append(
                    DiscardedCandidate(
                        evaluated,
                        f"no seleccionat: puntuació {total:.3f} inferior a la del millor "
                        f"({best_total:.3f})",
                    )
                )
            else:
                rejected.append(
                    DiscardedCandidate(evaluated, "rebutjat: " + evaluated.rejection_reason)
                )
        accepted.sort(key=lambda d: -(d.evaluated.score.total if d.evaluated.score else 0.0))
        rejected.sort(key=lambda d: -d.evaluated.importance)
        return tuple((*accepted, *rejected)[:limit])

    def summary(self, max_discarded: int = 5) -> dict[str, object]:
        """Resum estructurat: millor candidat, puntuacions, regles i descartats."""
        selected = self.selected
        return {
            "best": selected.candidate.text,
            "changed": not selected.candidate.is_identity,
            "applied_rules": [
                {"rule_id": t.rule_id, "before": t.text_before, "after": t.text_after}
                for t in selected.candidate.transformations
            ],
            "score": None if selected.score is None else selected.score.to_dict(),
            "n_candidates": len(self.candidates),
            "n_rejected": sum(1 for c in self.candidates if not c.accepted),
            "n_rejected_proposals": len(self.rejected_proposals),
            "discarded": [d.to_dict() for d in self.discarded(max_discarded)],
        }


@dataclass(frozen=True, slots=True)
class SentenceResult(_UnitResult):
    """Resultat del processament d'una frase."""

    index: int
    source_text: str
    span: Span
    output_text: str
    candidates: tuple[EvaluatedCandidate, ...]
    rejected_proposals: tuple[RejectedProposal, ...]
    protected_spans: tuple[ProtectedSpan, ...]
    notes: tuple[str, ...] = ()
    """Per què el motor no ha transformat (o ha limitat) aquesta frase."""

    @property
    def changed(self) -> bool:
        return self.output_text != self.source_text

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source_text": self.source_text,
            "span": self.span.to_dict(),
            "output_text": self.output_text,
            "changed": self.changed,
            "notes": list(self.notes),
            "transformations": [t.to_dict() for t in self.transformations],
            "alternatives": list(self.alternatives),
            "summary": self.summary(),
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected_proposals": [r.to_dict() for r in self.rejected_proposals],
            "protected_spans": [p.to_dict() for p in self.protected_spans],
        }


@dataclass(frozen=True, slots=True)
class ParagraphResult(_UnitResult):
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
    notes: tuple[str, ...] = ()
    """Per què no s'han fusionat frases del paràgraf, quan és rellevant."""

    @property
    def changed(self) -> bool:
        return self.output_text != self.intermediate_text

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source_text": self.source_text,
            "intermediate_text": self.intermediate_text,
            "span": self.span.to_dict(),
            "output_text": self.output_text,
            "changed": self.changed,
            "notes": list(self.notes),
            "transformations": [t.to_dict() for t in self.transformations],
            "alternatives": list(self.alternatives),
            "summary": self.summary(),
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
    dictionary_names: tuple[str, ...] = ()
    preferences_name: str = ""

    @property
    def notes(self) -> tuple[str, ...]:
        """Explicacions del motor sobre el que no ha transformat, sense repeticions."""
        seen = dict.fromkeys(
            note for unit in (*self.sentences, *self.paragraphs) for note in unit.notes
        )
        return tuple(seen)

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
        self._sources(lines)
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
            lines.extend(f"  ℹ {note}" for note in sentence.notes)
            for rejected in sentence.rejected_proposals:
                described = rejected.transformation.describe()
                lines.append(f"  ✘ Proposta descartada {described} — {rejected.reason}")
        for paragraph in self.paragraphs:
            if (
                len(paragraph.candidates) <= 1
                and not paragraph.rejected_proposals
                and not paragraph.notes
            ):
                continue
            lines.append("")
            lines.append(f"Paràgraf {paragraph.index + 1} (regles entre frases):")
            _explain_unit(
                lines, paragraph.intermediate_text, paragraph.output_text, paragraph.candidates
            )
            lines.extend(f"  ℹ {note}" for note in paragraph.notes)
            for rejected in paragraph.rejected_proposals:
                described = rejected.transformation.describe()
                lines.append(f"  ✘ Proposta descartada {described} — {rejected.reason}")
        return "\n".join(lines)

    def report(self, max_discarded: int = 5) -> str:
        """Informe de reescriptura: millor candidat, puntuacions, regles i descartats."""
        lines = ["=== Reescriptura ==="]
        lines.append(f"Conjunt de regles: {self.rule_set_name or '(cap)'}")
        if self.style_profile_name:
            lines.append(f"Estil de referència: {self.style_profile_name}")
        self._sources(lines)
        lines.append(
            f"Frases: {len(self.sentences)} · canviades: "
            f"{sum(1 for s in self.sentences if s.changed)} · candidats avaluats: "
            f"{self.n_candidates} · descartats: {self.n_rejected_candidates}"
        )
        for sentence in self.sentences:
            lines.append("")
            lines.append(f"Frase {sentence.index + 1}: «{sentence.source_text}»")
            _report_unit(lines, sentence, max_discarded)
            lines.extend(f"  ℹ {note}" for note in sentence.notes)
        for paragraph in self.paragraphs:
            if not paragraph.changed and len(paragraph.candidates) <= 1 and not paragraph.notes:
                continue
            lines.append("")
            lines.append(f"Paràgraf {paragraph.index + 1} (regles entre frases):")
            _report_unit(lines, paragraph, max_discarded)
            lines.extend(f"  ℹ {note}" for note in paragraph.notes)
        lines.append("")
        lines.append("Text resultant:")
        lines.append(self.output_text)
        return "\n".join(lines)

    def _sources(self, lines: list[str]) -> None:
        if self.dictionary_names:
            lines.append("Diccionaris actius: " + ", ".join(self.dictionary_names))
        if self.preferences_name:
            lines.append(f"Preferències de l'autor: {self.preferences_name}")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_text": self.source_text,
            "output_text": self.output_text,
            "changed": self.changed,
            "rule_set": self.rule_set_name,
            "rule_ids": list(self.rule_ids),
            "style_profile": self.style_profile_name,
            "dictionaries": list(self.dictionary_names),
            "preferences": self.preferences_name,
            "transformations": [t.to_dict() for t in self.transformations],
            "protected_spans": [p.to_dict() for p in self.protected_spans],
            "notes": list(self.notes),
            "sentences": [s.to_dict() for s in self.sentences],
            "paragraphs": [p.to_dict() for p in self.paragraphs],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _explain_unit(
    lines: list[str],
    source_text: str,
    output_text: str,
    candidates: Sequence[EvaluatedCandidate],
) -> None:
    selected = next((c for c in candidates if c.selected), None)
    if output_text != source_text and selected is not None:
        lines.append(f"  → «{output_text}»")
        lines.extend(f"  ✔ {t.describe()}" for t in selected.candidate.transformations)
    else:
        lines.append("  → sense canvis")
    if selected is not None:
        _explain_preferences(lines, selected)
    for evaluated in candidates:
        if evaluated.selected or evaluated.candidate.is_identity:
            continue
        if not evaluated.accepted:
            lines.append(
                f"  ✘ Candidat rebutjat «{evaluated.candidate.text}»: {evaluated.rejection_reason}"
            )
        elif evaluated.score is not None:
            rules = ", ".join(evaluated.candidate.rule_ids)
            lines.append(
                f"  · Candidat no seleccionat «{evaluated.candidate.text}» "
                f"[{rules}] (puntuació {evaluated.score.total:+.3f}: {evaluated.score.explanation})"
            )


def _explain_preferences(lines: list[str], selected: EvaluatedCandidate) -> None:
    """Per què les preferències explícites afavoreixen (o penalitzen) el candidat triat."""
    score = selected.score
    if score is None or not score.preference_explanation:
        return
    bonus = score.components.get("preferencies", 0.0)
    lines.append(f"  Preferències de l'autor ({bonus:+.3f}): {score.preference_explanation}")


def _report_unit(lines: list[str], unit: _UnitResult, max_discarded: int) -> None:
    selected = unit.selected
    if selected.candidate.is_identity:
        lines.append("  → sense canvis (cap candidat segur millora l'original)")
    else:
        lines.append(f"  → «{selected.candidate.text}»")
        lines.append("  Regles aplicades:")
        for t in selected.candidate.transformations:
            lines.append(f"    · {t.rule_id}: «{t.text_before}» → «{t.text_after}»")
    if selected.score is not None:
        lines.append(
            f"  Puntuacions: global {selected.score.total:+.3f} · "
            f"{selected.score.describe_dimensions()}"
        )
    _explain_preferences(lines, selected)
    discarded = unit.discarded(max_discarded)
    if discarded:
        lines.append("  Candidats descartats destacats:")
        for item in discarded:
            rules = ", ".join(item.evaluated.candidate.rule_ids) or "—"
            marker = "·" if item.evaluated.accepted else "✘"
            lines.append(f"    {marker} «{item.text}» [{rules}] — {item.reason}")
