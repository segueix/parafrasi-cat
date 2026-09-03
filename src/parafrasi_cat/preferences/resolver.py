"""Jerarquia de prioritats terminològiques.

Quan diverses fonts opinen sobre una mateixa forma, mana la primera d'aquesta
llista que en digui alguna cosa:

1. fragments protegits explícitament (``--protect``, ``protected_terms``,
   ``dictionaries/termes_protegits.txt``);
2. termes protegits dels diccionaris del projecte;
3. formes preferides, acceptades o a evitar dels diccionaris;
4. preferències explícites de l'autor (``preferences/author.yml`` i, després,
   el feedback manual);
5. empremta estadística de l'autor (``style/<autor>.json``);
6. preferències generals del motor.

Els nivells 1 i 2 són proteccions absolutes que aplica el protector i els
validadors: cap regla estilística no pot sobreescriure un terme protegit. El
:class:`PreferenceResolver` resol els nivells 1 a 4 i deixa la resta a
l'avaluador d'estil (nivell 5) i a la puntuació general (nivell 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from parafrasi_cat.dictionaries.dictionary import DictionarySet, normalize_term
from parafrasi_cat.preferences.author import AuthorPreferences
from parafrasi_cat.preferences.feedback import FeedbackStore


class PreferenceLevel(IntEnum):
    """Nivell de prioritat (1 = màxima)."""

    EXPLICIT_PROTECTION = 1
    DICTIONARY_PROTECTION = 2
    DICTIONARY = 3
    AUTHOR = 4
    FINGERPRINT = 5
    ENGINE = 6

    @property
    def label(self) -> str:
        return _LEVEL_LABELS[self]


_LEVEL_LABELS: dict[PreferenceLevel, str] = {
    PreferenceLevel.EXPLICIT_PROTECTION: "fragments protegits explícitament",
    PreferenceLevel.DICTIONARY_PROTECTION: "termes protegits dels diccionaris",
    PreferenceLevel.DICTIONARY: "formes preferides, acceptades o a evitar dels diccionaris",
    PreferenceLevel.AUTHOR: (
        "preferències explícites de l'autor (fitxer de preferències i feedback)"
    ),
    PreferenceLevel.FINGERPRINT: "empremta estadística de l'autor",
    PreferenceLevel.ENGINE: "preferències generals del motor",
}


def describe_hierarchy() -> str:
    return "\n".join(f"{level.value}. {level.label}" for level in PreferenceLevel)


@dataclass(frozen=True, slots=True)
class FormVerdict:
    """Què en diu la font més prioritària d'una forma.

    Atributs:
        form: Forma consultada.
        weight: Pes amb signe entre −1 (cal evitar-la) i +1 (cal preferir-la).
        level: Nivell de la jerarquia que ha decidit.
        source: Font concreta (diccionari, fitxer de preferències, feedback).
        reason: Motiu llegible.
    """

    form: str
    weight: float
    level: PreferenceLevel
    source: str
    reason: str

    def describe(self) -> str:
        return f"«{self.form}» {self.weight:+.2f} ({self.source}: {self.reason})"


class PreferenceResolver:
    """Resol el pes d'una forma seguint la jerarquia de prioritats."""

    def __init__(
        self,
        *,
        dictionaries: DictionarySet | None = None,
        author: AuthorPreferences | None = None,
        feedback: FeedbackStore | None = None,
        protected_terms: Iterable[str] = (),
    ) -> None:
        self._dictionaries = dictionaries if dictionaries else None
        self._author = author
        self._feedback = feedback
        self._protected = tuple(
            dict.fromkeys(" ".join(t.split()) for t in protected_terms if t.strip())
        )
        self._protected_keys = frozenset(normalize_term(t) for t in self._protected)

    @property
    def dictionaries(self) -> DictionarySet | None:
        return self._dictionaries

    @property
    def author(self) -> AuthorPreferences | None:
        return self._author

    @property
    def feedback(self) -> FeedbackStore | None:
        return self._feedback

    @property
    def active(self) -> bool:
        """Cert si hi ha alguna font de preferències (encara que no tingui formes)."""
        return bool(
            self._protected
            or self._dictionaries is not None
            or self._author is not None
            or self._feedback is not None
        )

    @property
    def forms(self) -> tuple[str, ...]:
        """Totes les formes sobre les quals alguna font té una opinió."""
        forms: list[str] = list(self._protected)
        if self._dictionaries is not None:
            forms.extend(self._dictionaries.forms)
        if self._author is not None:
            forms.extend(self._author.forms)
        if self._feedback is not None:
            forms.extend(self._feedback.forms)
        result: list[str] = []
        seen: set[str] = set()
        for form in forms:
            key = normalize_term(form)
            if key not in seen:
                seen.add(key)
                result.append(form)
        return tuple(result)

    def explicit_forms(self) -> frozenset[str]:
        """Claus normalitzades de les formes dels nivells 1 a 4 (manen sobre l'empremta)."""
        return frozenset(normalize_term(form) for form in self.forms)

    def resolve(self, form: str) -> FormVerdict | None:
        """Veredicte de la font més prioritària, o ``None`` si cap font en diu res."""
        key = normalize_term(form)
        if key in self._protected_keys:
            return FormVerdict(
                form,
                1.0,
                PreferenceLevel.EXPLICIT_PROTECTION,
                "protecció explícita",
                "terme protegit per l'usuari: cap regla el pot modificar",
            )
        if self._dictionaries is not None:
            protecting = self._dictionaries.protecting(form)
            if protecting is not None:
                entry = protecting.entry_for(form)
                term = entry.term if entry is not None else form
                return FormVerdict(
                    form,
                    1.0,
                    PreferenceLevel.DICTIONARY_PROTECTION,
                    f"diccionari «{protecting.name}»",
                    f"terme protegit («{term}»): cap regla el pot modificar",
                )
            match = self._dictionaries.lookup(form)
            if match is not None:
                reason = f"{match.status.label} per al terme «{match.entry.term}»"
                if match.entry.notes:
                    reason += f" ({match.entry.notes})"
                return FormVerdict(
                    form,
                    match.status.weight,
                    PreferenceLevel.DICTIONARY,
                    f"diccionari «{match.dictionary.name}»",
                    reason,
                )
        if self._author is not None:
            weight = self._author.weight_of(form)
            if weight is not None:
                return FormVerdict(
                    form,
                    2.0 * weight - 1.0,
                    PreferenceLevel.AUTHOR,
                    self._author.source_label,
                    self._author.reason_of(form) or "",
                )
        if self._feedback is not None:
            counts = self._feedback.counts_of(form)
            if counts is not None:
                weight = counts.weight(self._feedback.prior)
                return FormVerdict(
                    form,
                    2.0 * weight - 1.0,
                    PreferenceLevel.AUTHOR,
                    self._feedback.source_label,
                    f"l'autor l'ha marcada com a {counts.describe()} (pes {weight:.2f})",
                )
        return None

    def describe(self) -> str:
        lines = ["Fonts de preferències actives:"]
        if self._protected:
            lines.append(f"  1. termes protegits explícitament: {len(self._protected)}")
        if self._dictionaries is not None:
            lines.append("  2-3. diccionaris: " + ", ".join(self._dictionaries.names))
        if self._author is not None:
            lines.append(f"  4. {self._author.source_label}")
        if self._feedback is not None:
            lines.append(f"  4. {self._feedback.source_label} ({len(self._feedback)} variants)")
        if len(lines) == 1:
            lines.append("  (cap)")
        return "\n".join(lines)
