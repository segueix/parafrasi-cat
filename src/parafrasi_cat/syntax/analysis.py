"""Estructures i protocol de l'anàlisi sintàctica.

L'anàlisi sintàctica **només analitza**. No genera text, no completa frases,
no reescriu, no decideix estil i no inventa informació. La generació continua
sent exclusivament de les regles explícites, els diccionaris i la selecció
determinista de candidats.

És opcional: sense parser instal·lat, :class:`NullSyntax` no diu res i el
motor continua amb les heurístiques de sempre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Relacions de dependència universals que marquen un subjecte.
SUBJECT_DEPS = frozenset({"nsubj", "nsubj:pass", "csubj", "csubj:pass"})

#: Relacions que marquen un objecte o un atribut.
OBJECT_DEPS = frozenset({"obj", "iobj", "obl:arg"})

#: Relacions que obren una subordinada.
CLAUSE_DEPS = frozenset({"acl", "acl:relcl", "advcl", "ccomp", "xcomp", "csubj"})

#: Relacions de complement circumstancial.
MODIFIER_DEPS = frozenset({"obl", "obl:tmod", "obl:mod", "advmod", "nmod"})

#: Formes que neguen. Es comproven a part perquè perdre-les altera el sentit.
NEGATIONS = frozenset({"no", "mai", "cap", "ni", "gens", "tampoc"})


@dataclass(frozen=True, slots=True)
class SyntaxToken:
    """Un mot analitzat, amb la seva relació de dependència.

    ``head`` és l'índex del nucli dins de la mateixa frase; a l'arrel, apunta
    a si mateix. Els intervals són relatius al text analitzat.
    """

    index: int
    text: str
    lemma: str
    pos: str
    dep: str
    head: int
    start: int
    end: int
    gender: str | None = None
    number: str | None = None
    person: str | None = None

    @property
    def is_root(self) -> bool:
        return self.dep == "ROOT" or self.head == self.index

    @property
    def is_subject(self) -> bool:
        return self.dep in SUBJECT_DEPS

    @property
    def is_object(self) -> bool:
        return self.dep in OBJECT_DEPS

    @property
    def is_negation(self) -> bool:
        return self.lemma.lower() in NEGATIONS or self.text.lower() in NEGATIONS

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "text": self.text,
            "lemma": self.lemma,
            "pos": self.pos,
            "dep": self.dep,
            "head": self.head,
            "gender": self.gender,
            "number": self.number,
            "person": self.person,
        }


@dataclass(frozen=True, slots=True)
class SentenceSyntax:
    """Anàlisi sintàctica d'una frase.

    ``confident`` és fals quan el parser no ha pogut analitzar prou bé la
    frase; aleshores les regles han de recórrer a les heurístiques.
    """

    text: str
    tokens: tuple[SyntaxToken, ...] = ()
    confident: bool = True
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.tokens)

    @property
    def root(self) -> SyntaxToken | None:
        return next((t for t in self.tokens if t.is_root), None)

    @property
    def subjects(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_subject)

    @property
    def objects(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_object)

    @property
    def negations(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_negation)

    @property
    def clauses(self) -> tuple[SyntaxToken, ...]:
        """Nuclis de les subordinades (relatives, completives, adverbials)."""
        return tuple(t for t in self.tokens if t.dep in CLAUSE_DEPS)

    @property
    def coordinations(self) -> tuple[SyntaxToken, ...]:
        """Membres coordinats: perdre'n un canvia el contingut."""
        return tuple(t for t in self.tokens if t.dep == "conj")

    @property
    def n_finite_verbs(self) -> int:
        return sum(1 for t in self.tokens if t.pos in ("VERB", "AUX"))

    def main_subject(self) -> SyntaxToken | None:
        """Subjecte de l'oració principal, si n'hi ha un de sol i clar."""
        root = self.root
        if root is None:
            return None
        direct = [t for t in self.subjects if t.head == root.index]
        return direct[0] if len(direct) == 1 else None

    def subject_number(self) -> str | None:
        """Nombre del subjecte principal («sg» o «pl»), si el parser n'està segur."""
        subject = self.main_subject()
        return None if subject is None else subject.number

    def token_at(self, offset: int) -> SyntaxToken | None:
        """Mot que conté la posició de caràcter indicada."""
        return next((t for t in self.tokens if t.start <= offset < t.end), None)

    def tokens_in(self, start: int, end: int) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.start >= start and t.end <= end)

    def crosses_clause_boundary(self, start: int, end: int) -> bool:
        """Cert si l'interval parteix una subordinada o una coordinació pel mig.

        Serveix per no dividir ni reordenar allà on es trencaria una relació:
        si un membre coordinat o una subordinada queda a mitges, no es toca.
        """
        inside = self.tokens_in(start, end)
        if not inside:
            return False
        indices = {t.index for t in inside}
        for token in self.tokens:
            if token.dep not in CLAUSE_DEPS and token.dep != "conj":
                continue
            # El nucli d'una relació dins de l'interval ha de tenir el seu cap
            # també a dins; si no, la relació queda partida.
            if token.index in indices and token.head not in indices:
                return True
            if token.index not in indices and token.head in indices:
                return True
        return False

    def describe(self) -> str:
        root = self.root
        subject = self.main_subject()
        parts = [f"arrel: {root.text if root else '?'}"]
        if subject is not None:
            parts.append(f"subjecte: {subject.text} ({subject.number or 'nombre desconegut'})")
        if self.objects:
            parts.append("objecte: " + ", ".join(t.text for t in self.objects))
        if self.clauses:
            parts.append(f"subordinades: {len(self.clauses)}")
        if self.coordinations:
            parts.append(f"coordinacions: {len(self.coordinations)}")
        if self.negations:
            parts.append("negació: " + ", ".join(t.text for t in self.negations))
        return " · ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "confident": self.confident,
            "source": self.source,
            "tokens": [t.to_dict() for t in self.tokens],
        }


@runtime_checkable
class SyntaxProvider(Protocol):
    """Analitzador sintàctic local. Només analitza; mai no genera res."""

    @property
    def available(self) -> bool:
        """Cert si l'analitzador està instal·lat i carregat."""
        ...

    def parse(self, text: str) -> SentenceSyntax:
        """Anàlisi d'una frase. Buida si l'analitzador no hi és o no en sap prou."""
        ...


class NullSyntax:
    """Analitzador que no sap res. És el que hi ha si no s'ha instal·lat cap parser."""

    available = False

    def parse(self, text: str) -> SentenceSyntax:
        return SentenceSyntax(text, (), confident=False, source="null")


def agree(
    first: SyntaxToken | None, second: SyntaxToken | None, feature: str = "number"
) -> bool | None:
    """Cert si els dos mots comparteixen el tret; ``None`` si no se sap."""
    if first is None or second is None:
        return None
    left: object = getattr(first, feature)
    right: object = getattr(second, feature)
    if left is None or right is None:
        return None
    return bool(left == right)


def merge(*analyses: SentenceSyntax) -> SentenceSyntax:  # pragma: no cover - utilitat
    """Primera anàlisi amb contingut, per encadenar proveïdors."""
    for analysis in analyses:
        if analysis:
            return analysis
    return SentenceSyntax(analyses[0].text if analyses else "", (), confident=False)


def token_features(token: SyntaxToken) -> dict[str, str]:
    """Trets del mot en el vocabulari que fan servir les condicions de les regles."""
    features: dict[str, str] = {"lemma": token.lemma, "pos": token.pos, "dep": token.dep}
    for name in ("gender", "number", "person"):
        value = getattr(token, name)
        if value is not None:
            features[name] = value
    return features


DEFAULT_FIELDS: tuple[str, ...] = ("lemma", "pos", "dep", "gender", "number", "person")

_EMPTY: SentenceSyntax = SentenceSyntax("", (), confident=False, source="null")


def empty(text: str = "") -> SentenceSyntax:
    return SentenceSyntax(text, (), confident=False, source="null") if text else _EMPTY


__all__ = [
    "CLAUSE_DEPS",
    "DEFAULT_FIELDS",
    "MODIFIER_DEPS",
    "NEGATIONS",
    "OBJECT_DEPS",
    "SUBJECT_DEPS",
    "NullSyntax",
    "SentenceSyntax",
    "SyntaxProvider",
    "SyntaxToken",
    "agree",
    "empty",
    "merge",
    "token_features",
]
