"""Un candidat: una versió alternativa d'una frase amb les transformacions aplicades."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import (
    Transformation,
    TransformationFamily,
    apply_transformations,
)

MULTI_TRANSFORM = "MULTI_TRANSFORM"
#: Rendiments decreixents d'una mateixa família: la k-èsima aplicació val ``0.5^(k−1)``.
FAMILY_DECAY = 0.5
#: Traça addicional de les arquitectures absorbides dins d'una transformació composta.
CHAINED_ARCHITECTURES_KEY = "chained_architectures"
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,;:.!?»)])")
_ARCHITECTURE_KEYS = ("architecture", "movement", "block_kind")


@dataclass(frozen=True, slots=True)
class Candidate:
    """Versió alternativa d'una frase (o d'un paràgraf).

    Atributs:
        sentence_index: Índex de la frase (o del paràgraf) dins del document.
        source_text: Text original.
        text: Text del candidat (igual a ``source_text`` si és el candidat identitat).
        transformations: Transformacions aplicades, ordenades per posició i
            relatives a ``source_text``. Una transformació física pot contenir
            diverses operacions encadenades quan una reestructuració posterior
            engloba fragments ja transformats; la traça conserva totes les
            operacions reals.
    """

    sentence_index: int
    source_text: str
    text: str
    transformations: tuple[Transformation, ...] = ()

    @property
    def is_identity(self) -> bool:
        return not self.transformations and self.text == self.source_text

    @property
    def n_transformations(self) -> int:
        """Nombre real d'operacions, incloses les absorbides per composició."""
        return sum(t.operation_count for t in self.transformations)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        """Regles reals que han contribuït al candidat, en ordre traçable."""
        return tuple(rule for t in self.transformations for rule in t.operation_rule_ids)

    @property
    def families(self) -> tuple[TransformationFamily, ...]:
        """Famílies de totes les operacions, sense repeticions ni reparacions.

        No es mira només la família primària de cada fragment: si una operació
        posterior ha quedat absorbida dins d'una transformació composta, la
        família encadenada continua formant part de l'arquitectura del candidat.
        """
        seen: dict[TransformationFamily, None] = {}
        for transformation in self.transformations:
            for family in transformation.operation_families:
                if family is not TransformationFamily.REPAIR:
                    seen.setdefault(family, None)
        return tuple(seen)

    @property
    def structural_families(self) -> tuple[TransformationFamily, ...]:
        """Famílies estructurals presents (les que reorganitzen la frase o el paràgraf)."""
        return tuple(f for f in self.families if f.structural)

    @property
    def family_signature(self) -> str:
        """Signatura abstracta de famílies, compatible amb les versions anteriors."""
        families = self.families
        if not families:
            return TransformationFamily.ORIGINAL.value
        if len(families) == 1:
            return families[0].value
        return f"{MULTI_TRANSFORM}({'+'.join(sorted(f.value for f in families))})"

    @property
    def operation_architectures(self) -> tuple[str, ...]:
        """Identitat concreta de cada operació per distingir arquitectures equivalents.

        La família respon «què ha canviat»; aquesta traça respon «com». Dues
        reordenacions de la mateixa família poden ser diferents si una mou una
        subordinada i l'altra un complement, o si la mateixa regla mou el bloc
        en direccions diferents.
        """
        result: list[str] = []
        for transformation in self.transformations:
            primary = _architecture_id(transformation.rule_id, transformation.metadata)
            result.append(primary)
            chained = _csv(transformation.metadata.get(CHAINED_ARCHITECTURES_KEY))
            chained_rules = transformation.operation_rule_ids[1:]
            for index, rule_id in enumerate(chained_rules):
                result.append(chained[index] if index < len(chained) else rule_id)
        return tuple(result)

    @property
    def architecture_signature(self) -> str:
        """Signatura concreta de la ruta estructural, estable i determinista."""
        if self.is_identity:
            return TransformationFamily.ORIGINAL.value
        operations = self.operation_architectures
        return "ARCH(" + "+".join(operations) + ")" if operations else self.family_signature

    @property
    def signature(self) -> str:
        """Signatura usada per la cerca i la traça.

        Sense metadades arquitectòniques conserva exactament la signatura de
        família antiga. Quan una operació estructural declara ``architecture``,
        ``movement`` o ``block_kind`` —o n'ha absorbit una altra que ho feia—,
        la signatura incorpora la ruta concreta. Així el feix de paràgraf no
        confon dues reordenacions diferents només perquè totes dues són
        ``REORDER``.
        """
        base = self.family_signature
        if not self.is_structural or not _has_explicit_architecture(self.transformations):
            return base
        return f"{base}::{self.architecture_signature}"

    @property
    def diversity_signature(self) -> str:
        """Clau de diversitat del cercador.

        En candidats estructurals distingeix sempre les arquitectures concretes,
        fins i tot si una regla antiga encara no declara metadades específiques.
        En retocs superficials conserva la signatura de família perquè variants
        lèxiques no omplin el feix només pel seu ``rule_id``.
        """
        return self.architecture_signature if self.is_structural else self.family_signature

    def structural_degree(self) -> float:
        """Grau de reredacció estructural (0-1): només l'arquitectura lingüística.

        Hi compten únicament les operacions de famílies estructurals
        (reordenació, subordinació, canvi de construcció, divisió, fusió). Cap
        substitució lèxica, de connector, de puntuació ni de flexió verbal no hi
        suma res, per moltes que se n'apliquin.

        Quan diverses operacions han quedat absorbides dins d'un mateix fragment
        per composició profunda, totes les famílies conegudes continuen comptant;
        la mateixa família manté rendiments decreixents.
        """
        return _combine(self._impacts(structural=True))

    def surface_degree(self) -> float:
        """Grau de canvi superficial (0-1): mots, connectors, puntuació i flexió."""
        return _combine(self._impacts(structural=False))

    def _impacts(self, *, structural: bool) -> list[float]:
        by_family: dict[TransformationFamily, list[float]] = {}
        length = max(1, len(self.source_text))
        for transformation in self.transformations:
            coverage = min(1.0, transformation.changed_span.length / length)
            for index, family in enumerate(transformation.operation_families):
                if family.structural is not structural or family is TransformationFamily.REPAIR:
                    continue
                if structural:
                    weight = (
                        transformation.structural_weight
                        if index == 0 and family is transformation.family
                        else family.weight
                    )
                    reach = 1.0 if family.cross_sentence else 0.5 + 0.5 * coverage
                    impact = weight * transformation.confidence * reach
                else:
                    impact = family.surface_weight * transformation.confidence
                if impact > 0:
                    by_family.setdefault(family, []).append(impact)
        impacts: list[float] = []
        for values in by_family.values():
            for rank, value in enumerate(sorted(values, reverse=True)):
                impacts.append(value * FAMILY_DECAY**rank)
        return impacts

    @property
    def is_structural(self) -> bool:
        """Cert si alguna operació real canvia l'arquitectura de la frase."""
        return any(
            family.structural
            for transformation in self.transformations
            for family in transformation.operation_families
        )

    def normalized_text(self) -> str:
        """Text sense espais repetits ni espais davant de puntuació.

        Serveix per detectar candidats gairebé idèntics: dos textos que només
        difereixen en això no aporten cap alternativa real. Les majúscules sí
        que compten: canvien el text.
        """
        collapsed = " ".join(self.text.split())
        return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", collapsed)

    def change_ratio(self) -> float:
        """Proporció de caràcters canviats (0 = idèntic, 1 = completament diferent)."""
        if self.source_text == self.text:
            return 0.0
        return 1.0 - SequenceMatcher(a=self.source_text, b=self.text, autojunk=False).ratio()

    def result_spans(self) -> tuple[Span, ...]:
        """Interval que ocupa el ``text_after`` de cada transformació dins de ``text``."""
        spans: list[Span] = []
        shift = 0
        for transformation in self.transformations:
            start = transformation.changed_span.start + shift
            spans.append(Span(start, start + len(transformation.text_after)))
            shift += len(transformation.text_after) - transformation.changed_span.length
        return tuple(spans)

    def source_offset(self, offset: int) -> int | None:
        """Posició equivalent al text original, o ``None`` si cau en un tros canviat.

        Serveix per tornar a projectar sobre l'original una posició trobada al
        text del candidat (p. ex. el verb que una reparació ha de flexionar).
        """
        shift = 0
        for transformation in self.transformations:
            start = transformation.changed_span.start + shift
            end = start + len(transformation.text_after)
            if offset < start:
                return offset - shift
            if offset < end:
                return None
            shift += len(transformation.text_after) - transformation.changed_span.length
        return offset - shift

    def rule_at(self, offset: int) -> str:
        """Regla primària que ha escrit el fragment on cau la posició."""
        for transformation, span in zip(self.transformations, self.result_spans(), strict=True):
            if span.start <= offset < span.end:
                return transformation.rule_id
        return ""

    @classmethod
    def identity(cls, sentence_index: int, source_text: str) -> Candidate:
        return cls(sentence_index, source_text, source_text, ())

    @classmethod
    def from_transformations(
        cls,
        sentence_index: int,
        source_text: str,
        transformations: Iterable[Transformation],
    ) -> Candidate:
        ordered = tuple(sorted(transformations, key=lambda t: t.changed_span.start))
        return cls(
            sentence_index, source_text, apply_transformations(source_text, ordered), ordered
        )

    def describe(self) -> str:
        if self.is_identity:
            return "sense canvis"
        return "; ".join(t.describe() for t in self.transformations)

    def to_dict(self) -> dict[str, object]:
        return {
            "sentence_index": self.sentence_index,
            "source_text": self.source_text,
            "text": self.text,
            "transformations": [t.to_dict() for t in self.transformations],
            "operation_count": self.n_transformations,
            "operation_rule_ids": list(self.rule_ids),
            "operation_architectures": list(self.operation_architectures),
            "architecture_signature": self.architecture_signature,
            "change_ratio": round(self.change_ratio(), 4),
            "signature": self.signature,
            "family_signature": self.family_signature,
            "families": [f.value for f in self.families],
            "structural_families": [f.value for f in self.structural_families],
            "structural_degree": self.structural_degree(),
            "surface_degree": self.surface_degree(),
        }


def _architecture_id(rule_id: str, metadata: Mapping[str, str]) -> str:
    details = [
        f"{key}={metadata[key]}"
        for key in _ARCHITECTURE_KEYS
        if str(metadata.get(key, "")).strip()
    ]
    return rule_id if not details else f"{rule_id}[{';'.join(details)}]"


def _has_explicit_architecture(transformations: Iterable[Transformation]) -> bool:
    for transformation in transformations:
        if any(str(transformation.metadata.get(key, "")).strip() for key in _ARCHITECTURE_KEYS):
            return True
        if str(transformation.metadata.get(CHAINED_ARCHITECTURES_KEY, "")).strip():
            return True
    return False


def _csv(value: object) -> tuple[str, ...]:
    return tuple(item for item in str(value or "").split(",") if item)


def _combine(impacts: Iterable[float]) -> float:
    """Combina aportacions (0-1) com a probabilitats independents: ``1 − Π(1 − a)``."""
    remaining = 1.0
    for impact in impacts:
        remaining *= 1.0 - max(0.0, min(1.0, impact))
    return round(1.0 - remaining, 4)
