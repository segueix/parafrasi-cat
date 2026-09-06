"""Repetició de connectors dins d'una unitat: la que s'introdueix contra la que ja hi era.

Repetir un connector no és cap error. Un autor pot escriure «perquè… perquè» i
això forma part del seu estil. El que sí que és un defecte evitable és que el
motor **introdueixi** una repetició que l'original no tenia —«atès que… atès
que» on hi havia «perquè… perquè»— quan existeix una alternativa igual de
segura. Aquest mòdul mesura exactament això:

1. **Inventari accionable.** Només es miren les formes que les classes
   d'equivalència de connectors declaren (membres i objectius). Penalitzar la
   repetició d'una forma que el motor no pot variar no serviria de res, i
   deixaria fora l'única cosa que el sistema pot decidir. Les formes de més
   d'una paraula («atès que», «no obstant això») es reconeixen sobre els
   tokens, de manera que no depenen que el lexicó les tingui donades d'alta
   com a expressió.
2. **Distància.** Cada aparició es compara amb l'anterior de la mateixa forma i
   pesa ``1 / (1 + frases de distància)``: dins de la mateixa frase 1,00, a la
   següent 0,50, dues més enllà 0,33, tres 0,25… Decreix sempre, és acotat, no
   té cap llindar i s'explica en una línia. Fora de la unitat que es puntua
   (un altre paràgraf) no es mesura res.
3. **Introduïda contra heretada.** Es calcula la severitat per forma del
   candidat i la de l'original, i només es penalitza l'excés:
   ``introduïda(F) = max(0, severitat_candidat(F) - severitat_original(F))``.
   Si l'autor ja repetia «perquè», conservar-ho no costa res; canviar-ho per
   una repetició nova de «atès que» sí, perquè la forma nova no era repetida a
   l'original.

La penalització resultant és petita i mai no invalida res: és un desempat
entre candidats que ja han passat els validadors. Si no hi ha cap alternativa
segura, el text es queda com està.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.analyzer.tokens import TokenKind
from parafrasi_cat.style.adaptation import AdaptationContext

NEIGHBOUR_DISTANCE = 1
"""Distància que s'atribueix a la coincidència amb la unitat contigua del document."""


def distance_weight(distance: int) -> float:
    """Pes d'una repetició separada per ``distance`` frases: ``1 / (1 + d)``."""
    return 1.0 / (1.0 + max(0, distance))


@dataclass(frozen=True, slots=True)
class ConnectorUse:
    """Una aparició d'un connector de l'inventari, amb la frase on surt."""

    form: str
    sentence: int


@dataclass(frozen=True, slots=True)
class RepeatedConnector:
    """Una repetició detectada, amb la seva distància i si és nova."""

    form: str
    distance: int
    weight: float
    introduced: bool

    def describe(self) -> str:
        origin = "nova" if self.introduced else "ja era a l'original"
        frases = "la mateixa frase" if self.distance == 0 else f"{self.distance} frases"
        return f"«{self.form}» a {frases} ({origin})"

    def to_dict(self) -> dict[str, object]:
        return {
            "form": self.form,
            "distance": self.distance,
            "weight": round(self.weight, 4),
            "introduced": self.introduced,
        }


@dataclass(frozen=True, slots=True)
class RepetitionAssessment:
    """Repetició de connectors d'un text respecte del seu original."""

    penalty: float = 0.0
    """Severitat de la repetició **introduïda**, entre 0 i 1."""
    profile: tuple[str, ...] = ()
    """Seqüència de connectors de l'inventari, en ordre d'aparició."""
    repeats: tuple[RepeatedConnector, ...] = field(default_factory=tuple)

    @property
    def penalised(self) -> bool:
        return self.penalty > 0.0

    @property
    def introduced(self) -> tuple[RepeatedConnector, ...]:
        return tuple(r for r in self.repeats if r.introduced)

    @property
    def forms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.form for r in self.introduced))

    def describe(self) -> str:
        return "; ".join(r.describe() for r in self.introduced)

    def to_dict(self) -> dict[str, object]:
        return {
            "penalty": round(self.penalty, 4),
            "profile": list(self.profile),
            "repeats": [r.to_dict() for r in self.repeats],
            "introduced": [r.to_dict() for r in self.introduced],
        }


class ConnectorRepetition:
    """Perfil de connectors d'un text i repetició introduïda respecte d'un original."""

    def __init__(self, analyzer: Analyzer, forms: Iterable[str]) -> None:
        self._analyzer = analyzer
        phrases: dict[tuple[str, ...], str] = {}
        for form in forms:
            words = tuple(normalize_form(form).split())
            if words:
                phrases.setdefault(words, " ".join(words))
        self._phrases = phrases
        self._longest = max((len(words) for words in phrases), default=0)
        self._cache: dict[str, tuple[ConnectorUse, ...]] = {}

    @property
    def forms(self) -> frozenset[str]:
        """Formes que l'inventari reconeix (les que tenen alguna alternativa segura)."""
        return frozenset(self._phrases.values())

    @property
    def available(self) -> bool:
        return bool(self._phrases)

    # --- perfil ---------------------------------------------------------------------------

    def uses(self, text: str) -> tuple[ConnectorUse, ...]:
        """Connectors de l'inventari que apareixen al text, amb l'índex de frase."""
        if not text or not self._phrases:
            return ()
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        found: list[ConnectorUse] = []
        for index, sentence in enumerate(self._analyzer.analyze(text).sentences):
            words = [normalize_form(t.text) for t in sentence.tokens if t.kind is TokenKind.WORD]
            position = 0
            while position < len(words):
                match = self._match_at(words, position)
                if match is None:
                    position += 1
                    continue
                form, length = match
                found.append(ConnectorUse(form, index))
                position += length
        result = tuple(found)
        self._cache[text] = result
        return result

    def _match_at(self, words: Sequence[str], position: int) -> tuple[str, int] | None:
        """Forma més llarga de l'inventari que comença en aquesta posició."""
        limit = min(self._longest, len(words) - position)
        for length in range(limit, 0, -1):
            form = self._phrases.get(tuple(words[position : position + length]))
            if form is not None:
                return form, length
        return None

    def profile(self, text: str) -> tuple[str, ...]:
        """Seqüència de formes de l'inventari, en ordre d'aparició."""
        return tuple(use.form for use in self.uses(text))

    # --- repetició ------------------------------------------------------------------------

    def pairs(
        self, uses: Sequence[ConnectorUse], context: AdaptationContext | None = None
    ) -> tuple[tuple[str, int], ...]:
        """Repeticions (forma, distància en frases) del text i, si escau, del seu veïnat."""
        previous: dict[str, int] = {}
        found: list[tuple[str, int]] = []
        for use in uses:
            last = previous.get(use.form)
            if last is not None:
                found.append((use.form, use.sentence - last))
            previous[use.form] = use.sentence
        found.extend(self._boundary(uses, context))
        return tuple(found)

    def severity(self, pairs: Sequence[tuple[str, int]]) -> dict[str, float]:
        """Severitat acumulada per forma, amb el pes que li dona la distància."""
        totals: dict[str, float] = {}
        for form, distance in pairs:
            totals[form] = totals.get(form, 0.0) + distance_weight(distance)
        return totals

    def assess(
        self,
        text: str,
        source_text: str = "",
        context: AdaptationContext | None = None,
    ) -> RepetitionAssessment:
        """Repetició de connectors del text, descomptant la que l'original ja tenia."""
        if not self._phrases or not text:
            return RepetitionAssessment()
        uses = self.uses(text)
        if not uses:
            return RepetitionAssessment()
        candidate_pairs = self.pairs(uses, context)
        if not candidate_pairs:
            return RepetitionAssessment(profile=tuple(use.form for use in uses))
        # Sense original de referència no es pot distingir la repetició nova de la
        # que l'autor ja havia escrit: davant del dubte, no es penalitza res.
        source_uses = self.uses(source_text) if source_text and source_text != text else uses
        current = self.severity(candidate_pairs)
        inherited = self.severity(self.pairs(source_uses, context))
        introduced = {
            form: max(0.0, weight - inherited.get(form, 0.0)) for form, weight in current.items()
        }
        return RepetitionAssessment(
            penalty=round(min(1.0, sum(introduced.values())), 4),
            profile=tuple(use.form for use in uses),
            repeats=tuple(
                RepeatedConnector(form, distance, distance_weight(distance), introduced[form] > 0.0)
                for form, distance in candidate_pairs
            ),
        )

    def _boundary(
        self, uses: Sequence[ConnectorUse], context: AdaptationContext | None
    ) -> list[tuple[str, int]]:
        """Coincidència amb el connector contigu de la unitat anterior o següent.

        Serveix per a les unitats que es puntuen soles (una frase, amb la resta
        del document al voltant). Dins d'un paràgraf, la distància real entre
        frases ja la mesura ``pairs``; en un altre paràgraf no es mesura res.
        """
        if context is None or not uses:
            return []
        known = self.forms
        before = [form for form in context.before.connectors if form in known]
        after = [form for form in context.after.connectors if form in known]
        found: list[tuple[str, int]] = []
        if before and before[-1] == uses[0].form:
            found.append((uses[0].form, NEIGHBOUR_DISTANCE))
        if after and after[0] == uses[-1].form:
            found.append((uses[-1].form, NEIGHBOUR_DISTANCE))
        return found


def connector_forms(rules: Iterable[object]) -> tuple[str, ...]:
    """Formes de connector amb alternativa segura, segons les regles d'equivalència.

    Es llegeixen les classes de les regles actives (membres i objectius): són
    exactament les formes que el motor pot intercanviar. Una forma que no pot
    variar no entra a l'inventari, perquè penalitzar-ne la repetició empenyeria
    la tria cap a canvis que no tenen res a veure amb el connector.
    """
    forms: dict[str, None] = {}
    for rule in rules:
        classes = getattr(rule, "classes", None)
        if not classes:
            continue
        for connector_class in classes:
            for member in (*connector_class.members, *connector_class.targets):
                forms.setdefault(normalize_form(member.form), None)
    return tuple(forms)


__all__ = [
    "ConnectorRepetition",
    "ConnectorUse",
    "RepeatedConnector",
    "RepetitionAssessment",
    "connector_forms",
    "distance_weight",
]
