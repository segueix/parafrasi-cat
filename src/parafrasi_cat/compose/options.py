"""Tria de redaccions el més diferents possible entre elles.

El motor genera molts candidats segurs d'una mateixa frase, i sovint la
majoria s'assemblen: canvien un connector, o mouen el mateix bloc. Ensenyar-ne
tres de gairebé iguals no ajuda ningú a decidir. Aquí es trien les que **més
es diferencien**, amb un criteri explícit i determinista.

La distància entre dues redaccions té dues parts, totes dues entre 0 i 1:

- **arquitectura**: si tenen la mateixa signatura estructural, 0; si en tenen
  de diferents, 1. És el que distingeix una divisió d'una reordenació.
- **redacció**: ``1 - semblança`` de les seqüències de paraules. És el que
  distingeix dues divisions que parteixen la frase per llocs diferents.

La distància total pesa el doble l'arquitectura, perquè és la diferència que
es veu llegint. La tria és voraç: primer la millor redacció segons el
puntuador, reservant una plaça per al candidat validat amb més canvi
estructural. Després, cada cop, la que és més lluny de totes les triades.
Amb empats, mana la puntuació i després l'ordre d'arribada, de manera que la
mateixa entrada dona sempre la mateixa llista.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from parafrasi_cat.candidates.candidate import Candidate
from parafrasi_cat.pipeline.result import EvaluatedCandidate
from parafrasi_cat.synonyms.suggester import TokenOptions

ARCHITECTURE_WEIGHT = 2.0
"""Pes de la diferència d'arquitectura dins de la distància (la redacció val 1)."""

DEFAULT_WANTED = 3
"""Redaccions que la pantalla de composició demana de cada frase."""


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.lower().split())


def distance(first: Candidate, second: Candidate) -> float:
    """Com de diferents són dues redaccions, entre 0 i 1."""
    architecture = 0.0 if first.signature == second.signature else 1.0
    wording = 1.0 - SequenceMatcher(None, _words(first.text), _words(second.text)).ratio()
    return (ARCHITECTURE_WEIGHT * architecture + wording) / (ARCHITECTURE_WEIGHT + 1.0)


def choose_options(
    candidates: Sequence[EvaluatedCandidate], wanted: int = DEFAULT_WANTED
) -> tuple[EvaluatedCandidate, ...]:
    """Les ``wanted`` redaccions més diferents entre elles, la millor al davant.

    Només entren candidats acceptats i diferents de l'original: l'original ja
    hi és sempre, com a punt de partida, i no cal comptar-lo dues vegades.
    """
    pool = [
        evaluated
        for evaluated in candidates
        if evaluated.accepted and not evaluated.candidate.is_identity
    ]
    if not pool or wanted <= 0:
        return ()
    position = {id(evaluated): n for n, evaluated in enumerate(pool)}
    structural = [e for e in pool if e.candidate.is_structural
                  and e.candidate.structural_degree() > 0]
    reserved = max(structural, key=lambda e: (
        e.candidate.structural_degree(), e.candidate.change_ratio(),
        _total(e), -position[id(e)],
    )) if structural else None
    if wanted == 1 and reserved is not None:
        return (reserved,)
    ranked = sorted(pool, key=lambda e: (-_total(e), position[id(e)]))
    seen: set[str] = set()
    chosen: list[EvaluatedCandidate] = []
    # Prefer the structural trace when identical text has multiple derivations.
    if reserved is not None:
        ranked = [reserved] + [e for e in ranked if e is not reserved]
    for evaluated in ranked:
        text = evaluated.candidate.normalized_text()
        if text in seen:
            continue
        seen.add(text)
        chosen.append(evaluated)
    if len(chosen) <= wanted:
        return tuple(sorted(chosen, key=lambda e: (-_total(e), position[id(e)])))
    # Keep the highest scoring wording first, then the reserved alternative.
    chosen.sort(key=lambda e: (-_total(e), position[id(e)]))
    picked = [chosen[0]]
    if reserved is not None and reserved is not chosen[0]:
        picked.append(reserved)
    rest = [e for e in chosen if all(e is not p for p in picked)]
    while len(picked) < wanted and rest:
        best = max(
            rest,
            key=lambda e: (
                min(distance(e.candidate, p.candidate) for p in picked),
                _total(e),
                -position[id(e)],
            ),
        )
        picked.append(best)
        rest.remove(best)
    return tuple(picked)


def option_group(candidate: Candidate) -> str:
    """Group only known voice/tense variants; never merge unrelated movements.

    This is presentation metadata, not a semantic-equivalence validator.
    Unknown or mixed structural paths retain their individual wording.
    """
    operations = candidate.operation_architectures
    voice = tuple(op for op in operations if op.startswith("veu.activa_passiva["))
    if len(voice) == 1 and all(
        op in voice or op.split("[", 1)[0] in {
            "verbal.perifrastic_a_simple", "verbal.simple_a_perifrastic"
        } for op in operations
    ):
        return voice[0]
    return candidate.normalized_text()


def choose_groups(candidates, wanted=DEFAULT_WANTED):
    """Select representatives with the existing selector, retain their variants."""
    groups = {}
    for evaluated in candidates:
        if evaluated.accepted and not evaluated.candidate.is_identity:
            bucket = groups.setdefault(option_group(evaluated.candidate), [])
            if not any(e.candidate.normalized_text() == evaluated.candidate.normalized_text()
                       for e in bucket):
                bucket.append(evaluated)
    def direct(e):
        rules = [r for t in e.candidate.transformations for r in t.operation_rule_ids]
        return ("nominal.verb_a_nom" in rules,
                "verbal.perifrastic_a_simple" in rules, -_total(e))
    for bucket in groups.values():
        bucket.sort(key=direct)
    representatives = choose_options([b[0] for b in groups.values()], wanted)
    representatives = sorted(representatives, key=lambda e: direct(e)[0])
    return tuple(tuple(groups[option_group(e.candidate)]) for e in representatives)


def _total(evaluated: EvaluatedCandidate) -> float:
    return evaluated.score.total if evaluated.score is not None else 0.0


@dataclass(frozen=True, slots=True)
class DraftOption:
    """Una redacció que la persona pot triar i editar."""

    option_id: str
    text: str
    original: bool = False
    """Cert per al text tal com el va escriure qui l'ha portat."""
    variant_of: str = ""
    signature: str = "ORIGINAL"
    structural_degree: float = 0.0
    change_ratio: float = 0.0
    summary: str = ""
    """Què s'hi ha canviat, en poques paraules."""
    rules: tuple[str, ...] = ()
    tokens: tuple[TokenOptions, ...] = field(default_factory=tuple)
    """Fragments amb alternatives, en ordre d'aparició dins de ``text``."""

    @property
    def editable(self) -> bool:
        return any(token.clickable for token in self.tokens)

    def to_dict(self) -> dict[str, object]:
        return {
            "option_id": self.option_id,
            "text": self.text,
            "original": self.original,
            "variant_of": self.variant_of,
            "signature": self.signature,
            "structural_degree": self.structural_degree,
            "structural_change_score": self.structural_degree,
            "change_ratio": self.change_ratio,
            "summary": self.summary,
            "rules": list(self.rules),
            "editable": self.editable,
            "tokens": [token.to_dict() for token in self.tokens],
        }


@dataclass(frozen=True, slots=True)
class SentenceDraft:
    """Una frase del paràgraf amb les redaccions que se n'ofereixen."""

    index: int
    source_text: str
    options: tuple[DraftOption, ...]
    note: str = ""
    """Per què no n'hi ha tres, quan no n'hi ha tres."""

    diagnostics: dict[str, object] = field(default_factory=dict)
    """Traça de la generació i dels filtres, sense tornar a executar-los."""

    @property
    def n_rewrites(self) -> int:
        return sum(1 for option in self.options if not option.original and not option.variant_of)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "source_text": self.source_text,
            "note": self.note,
            "n_rewrites": self.n_rewrites,
            "diagnostics": self.diagnostics,
            "options": [option.to_dict() for option in self.options],
        }


__all__ = [
    "ARCHITECTURE_WEIGHT",
    "DEFAULT_WANTED",
    "DraftOption",
    "SentenceDraft",
    "choose_options",
    "distance",
]
