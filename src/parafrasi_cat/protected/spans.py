"""Estructura ``ProtectedSpan``: un fragment intocable del text."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.core.spans import Span


class ProtectionKind(StrEnum):
    """Motiu pel qual un fragment queda protegit."""

    PROPER_NOUN = "proper_noun"
    DATE = "date"
    NUMBER = "number"
    ROMAN_NUMERAL = "roman_numeral"
    CITATION = "citation"
    QUOTED_TEXT = "quoted_text"
    USER_TERM = "user_term"

    @property
    def label(self) -> str:
        """Etiqueta en català per als informes."""
        return _KIND_LABELS[self]


_KIND_LABELS: dict[ProtectionKind, str] = {
    ProtectionKind.PROPER_NOUN: "nom propi",
    ProtectionKind.DATE: "data",
    ProtectionKind.NUMBER: "xifra",
    ProtectionKind.ROMAN_NUMERAL: "número romà",
    ProtectionKind.CITATION: "citació",
    ProtectionKind.QUOTED_TEXT: "text entre cometes",
    ProtectionKind.USER_TERM: "terme protegit per l'usuari",
}


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    """Fragment del text que cap transformació pot tocar.

    Atributs:
        span: Posició del fragment (relativa al text on s'ha detectat).
        text: Contingut exacte del fragment.
        kind: Motiu de la protecció.
        detector_id: Identificador del detector que l'ha trobat.
        note: Informació addicional opcional (p. ex. el terme d'usuari que ha coincidit).
    """

    span: Span
    text: str
    kind: ProtectionKind
    detector_id: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.span.length != len(self.text):
            raise ValueError(
                f"La longitud de l'interval ({self.span.length}) no coincideix amb el text "
                f"«{self.text}» ({len(self.text)})"
            )

    @property
    def start(self) -> int:
        return self.span.start

    @property
    def end(self) -> int:
        return self.span.end

    def overlaps(self, span: Span) -> bool:
        return self.span.overlaps(span)

    def shift(self, offset: int) -> ProtectedSpan:
        return ProtectedSpan(
            self.span.shift(offset), self.text, self.kind, self.detector_id, self.note
        )

    def describe(self) -> str:
        return f"[{self.kind.label}] «{self.text}» ({self.start}-{self.end})"

    def to_dict(self) -> dict[str, object]:
        return {
            "span": self.span.to_dict(),
            "text": self.text,
            "kind": self.kind.value,
            "detector_id": self.detector_id,
            "note": self.note,
        }
