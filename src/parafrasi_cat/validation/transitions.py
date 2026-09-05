"""Matriu explícita de transicions entre categories epistemològiques.

Les categories ordenen la força expressada pel text, de menys a més:

    LIMITATION (què no es pot establir) < HYPOTHESIS (possibilitat)
    < INFERENCE (què es pot plantejar o deduir) < EVIDENCE (què es documenta,
    s'atribueix a una font o es dona per establert)

i ``UNKNOWN`` és la forma no marcada. Cap transformació pot pujar per aquesta
escala: una hipòtesi no esdevé inferència ni evidència, una limitació no
desapareix, i cap afirmació no marcada no es converteix en evidència. Les
transicions ``RULE_ONLY`` només les pot fer una regla que ho declari
(``allows_epistemic_change``); les ``FORBIDDEN`` no les pot fer cap regla.

Reduir una redundància («sembla que podria ser possible que» → «podria ser
que») no és cap transició: la categoria més feble es conserva i només
desapareix un marcador que la repetia. Ho autoritzen les regles amb
``reduces_epistemic_redundancy``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.validation.categories import EpistemicCategory


class Transition(StrEnum):
    ALLOWED = "allowed"
    RULE_ONLY = "rule_only"
    FORBIDDEN = "forbidden"


_E, _I, _H, _L, _U = (
    EpistemicCategory.EVIDENCE,
    EpistemicCategory.INFERENCE,
    EpistemicCategory.HYPOTHESIS,
    EpistemicCategory.LIMITATION,
    EpistemicCategory.UNKNOWN,
)

#: (categoria original, categoria del candidat) → transició permesa.
TRANSITIONS: Mapping[tuple[EpistemicCategory, EpistemicCategory], Transition] = {
    # Mantenir la categoria sempre és possible.
    **{(c, c): Transition.ALLOWED for c in EpistemicCategory},
    # Una limitació mai no es debilita ni es converteix en res més.
    (_L, _H): Transition.FORBIDDEN,
    (_L, _I): Transition.FORBIDDEN,
    (_L, _E): Transition.FORBIDDEN,
    (_L, _U): Transition.FORBIDDEN,
    # Una hipòtesi no puja a inferència ni a evidència; només una regla explícita
    # pot reformular-la com a inferència, i mai com a evidència o afirmació.
    (_H, _I): Transition.RULE_ONLY,
    (_H, _E): Transition.FORBIDDEN,
    (_H, _U): Transition.FORBIDDEN,
    (_H, _L): Transition.FORBIDDEN,
    # Una inferència no esdevé evidència; debilitar-la a hipòtesi és cosa d'una regla.
    (_I, _E): Transition.FORBIDDEN,
    (_I, _U): Transition.FORBIDDEN,
    (_I, _H): Transition.RULE_ONLY,
    (_I, _L): Transition.FORBIDDEN,
    # L'evidència no es debilita per sota d'inferència, i mai no es perd.
    (_E, _I): Transition.RULE_ONLY,
    (_E, _H): Transition.FORBIDDEN,
    (_E, _L): Transition.FORBIDDEN,
    (_E, _U): Transition.FORBIDDEN,
    # Afegir un marcador a una afirmació no marcada: mai evidència inventada;
    # la resta només amb una regla que ho declari.
    (_U, _E): Transition.FORBIDDEN,
    (_U, _I): Transition.RULE_ONLY,
    (_U, _H): Transition.RULE_ONLY,
    (_U, _L): Transition.RULE_ONLY,
}


def transition_between(before: EpistemicCategory, after: EpistemicCategory) -> Transition:
    """Transició declarada a la matriu per a un canvi de categoria."""
    return TRANSITIONS[(before, after)]


@dataclass(frozen=True, slots=True)
class TransitionVerdict:
    """Resultat de comparar els recomptes per categoria d'un original i d'un candidat."""

    transition: Transition
    before: EpistemicCategory
    after: EpistemicCategory
    detail: str

    def allowed(self, *, authorized: bool) -> bool:
        if self.transition is Transition.ALLOWED:
            return True
        if self.transition is Transition.RULE_ONLY:
            return authorized
        return False

    def describe(self) -> str:
        return f"transició {self.before.label} → {self.after.label}: {self.detail}"


def _strongest(counts: Counter[EpistemicCategory]) -> EpistemicCategory:
    ranked = [c for c in counts if counts[c] > 0 and c.rank is not None]
    return max(ranked, key=lambda c: c.rank or 0) if ranked else EpistemicCategory.UNKNOWN


def _weakest(counts: Counter[EpistemicCategory]) -> EpistemicCategory:
    ranked = [c for c in counts if counts[c] > 0 and c.rank is not None]
    return min(ranked, key=lambda c: c.rank or 0) if ranked else EpistemicCategory.UNKNOWN


def check_categories(
    before: Counter[EpistemicCategory],
    after: Counter[EpistemicCategory],
    *,
    redundancy: bool = False,
) -> TransitionVerdict | None:
    """Veredicte del canvi de categories entre l'original i el candidat.

    ``None`` si els recomptes coincideixen (o si només s'ha reduït una
    redundància i ``redundancy`` ho autoritza: la categoria més feble es
    conserva i no n'apareix cap de nova). Altrament, el veredicte diu quina
    transició de la matriu s'aplica.
    """
    before = Counter({c: n for c, n in before.items() if c is not EpistemicCategory.UNKNOWN})
    after = Counter({c: n for c, n in after.items() if c is not EpistemicCategory.UNKNOWN})
    if before == after:
        return None
    lost = before - after
    gained = after - before
    if not gained and after and redundancy and _weakest(after) is _weakest(before):
        return None  # redundància reduïda: la força més feble es manté
    if not gained:
        # Ha desaparegut un marcador i cap altre no el substitueix: afirmació no marcada.
        source = _weakest(lost)
        return TransitionVerdict(
            transition_between(source, EpistemicCategory.UNKNOWN),
            source,
            EpistemicCategory.UNKNOWN,
            "es perd el marcador i la formulació queda com una afirmació",
        )
    if not lost:
        target = _strongest(gained)
        return TransitionVerdict(
            transition_between(EpistemicCategory.UNKNOWN, target),
            EpistemicCategory.UNKNOWN,
            target,
            "s'afegeix un marcador que l'original no tenia",
        )
    source = _weakest(lost)
    target = _strongest(gained)
    transition = transition_between(source, target)
    if (target.rank or 0) > (source.rank or 0):
        detail = "augmenta la certesa expressada"
    elif (target.rank or 0) < (source.rank or 0):
        detail = "redueix la certesa expressada"
    else:
        detail = "canvia la funció epistemològica"
    return TransitionVerdict(transition, source, target, detail)


__all__ = [
    "TRANSITIONS",
    "Transition",
    "TransitionVerdict",
    "check_categories",
    "transition_between",
]
