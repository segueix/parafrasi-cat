"""Interfície base de les regles i contextos d'aplicació.

Hi ha dos àmbits de regla:

- :class:`Rule` treballa sobre una frase (:class:`RuleContext`);
- :class:`ParagraphRule` treballa sobre un paràgraf sencer
  (:class:`ParagraphContext`), per a transformacions entre frases (fusió).

En tots dos casos la regla **proposa** transformacions explícites i
comprovables; mai no les aplica ni redacta lliurement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import Transformation, TransformationType
from parafrasi_cat.morphology.provider import MorphologyProvider, NullMorphology
from parafrasi_cat.protected.spans import ProtectedSpan
from parafrasi_cat.style.profile import StyleProfile
from parafrasi_cat.syntax.analysis import NullSyntax, SentenceSyntax, SyntaxProvider

#: Marge sobre la longitud de frase preferida quan l'autor no fixa cap màxim.
#: Una frase pot passar mig cop de llarg del que l'autor acostuma a escriure;
#: més enllà, ja no és el seu estil.
LENGTH_MARGIN = 1.5


def protected_conflict(
    text: str, protected_spans: Sequence[ProtectedSpan], span: Span, text_after: str
) -> str | None:
    """Explica per què una substitució de ``span`` per ``text_after`` violaria la protecció.

    Un fragment protegit pot quedar *dins* del tros substituït (p. ex. quan es
    reordena una frase) sempre que aparegui intacte al text nou tantes vegades
    com abans. Retorna ``None`` si no hi ha conflicte.
    """
    text_before = span.slice(text)
    for protected in protected_spans:
        if not protected.overlaps(span):
            continue
        if not span.contains(protected.span):
            return f"trenca el fragment protegit {protected.describe()}"
        if text_after.count(protected.text) < text_before.count(protected.text):
            return f"altera el fragment protegit {protected.describe()}"
    return None


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Tot el que una regla de frase pot consultar per proposar transformacions.

    Els intervals de ``protected_spans`` i dels tokens de ``sentence`` són
    relatius al text de la frase.
    """

    sentence: Sentence
    protected_spans: tuple[ProtectedSpan, ...] = ()
    document_text: str = ""
    style_profile: StyleProfile | None = None
    morphology: MorphologyProvider = field(default_factory=NullMorphology)
    lexicon: ClosedClassLexicon | None = None
    syntax: SyntaxProvider = field(default_factory=NullSyntax)
    """Analitzador sintàctic local. Només l'usen les regles que el demanen."""
    analysis: SentenceSyntax | None = None
    """Anàlisi ja calculada per la canonada, per no analitzar dues vegades el mateix."""
    notes: list[str] = field(default_factory=list, compare=False, repr=False)
    """On les regles deixen dit per què no han transformat res, quan és rellevant."""

    def note(self, message: str) -> None:
        """Apunta una explicació que el motor ensenyarà amb el resultat."""
        if message not in self.notes:
            self.notes.append(message)

    @property
    def text(self) -> str:
        return self.sentence.text

    def parse(self) -> SentenceSyntax:
        """Anàlisi sintàctica de la frase (buida si no hi ha parser instal·lat)."""
        if self.analysis is not None:
            return self.analysis
        return self.syntax.parse(self.text)

    def overlapping_protected(self, span: Span) -> tuple[ProtectedSpan, ...]:
        return tuple(p for p in self.protected_spans if p.overlaps(span))

    def is_protected(self, span: Span) -> bool:
        """Cert si l'interval toca algun fragment protegit."""
        return any(p.overlaps(span) for p in self.protected_spans)

    def protected_conflict(self, span: Span, text_after: str) -> str | None:
        """Motiu pel qual substituir ``span`` per ``text_after`` alteraria contingut protegit."""
        return protected_conflict(self.text, self.protected_spans, span, text_after)

    def preserves_protected(self, span: Span, text_after: str) -> bool:
        return self.protected_conflict(span, text_after) is None


@dataclass(frozen=True, slots=True)
class ParagraphContext:
    """Context d'una regla de paràgraf.

    ``text`` és el text actual del paràgraf (després de les transformacions de
    frase) i ``sentences`` les seves frases, amb intervals relatius al paràgraf.
    ``source_text`` és el text original del paràgraf.
    """

    text: str
    sentences: tuple[Sentence, ...]
    protected_spans: tuple[ProtectedSpan, ...] = ()
    source_text: str = ""
    lexicon: ClosedClassLexicon | None = None
    syntax: SyntaxProvider = field(default_factory=NullSyntax)
    style_profile: StyleProfile | None = None
    preferred_sentence_length: int | None = None
    """Longitud de frase preferida per l'autor, en paraules (``None`` si no en fixa cap)."""
    max_sentence_length: int | None = None
    """Longitud màxima acceptable, en paraules. Cap regla no la pot superar."""
    notes: list[str] = field(default_factory=list, compare=False, repr=False)
    """On les regles deixen dit per què no han transformat res, quan és rellevant."""

    def note(self, message: str) -> None:
        """Apunta una explicació que el motor ensenyarà amb el resultat."""
        if message not in self.notes:
            self.notes.append(message)

    def length_limit(self) -> tuple[int | None, str]:
        """Paraules màximes d'una frase i d'on surt el límit.

        Es tenen en compte, i mana la més restrictiva:

        - el màxim explícit de l'autor (``max_sentence_length``);
        - la distribució de la seva empremta (mediana més rang interquartílic);
        - la longitud preferida amb un marge, si no hi ha res més.

        Un perfil d'estil genèric no compta: la mesura de com escriu l'autor és
        l'empremta calculada a partir dels seus textos. Sense cap d'aquestes
        dades no hi ha límit i decideix la regla.
        """
        limits: list[tuple[int, str]] = []
        if self.max_sentence_length is not None:
            limits.append((self.max_sentence_length, "el màxim que ha fixat l'autor"))
        profile = self.style_profile
        if profile is not None and profile.preferences is not None:
            observed = int(profile.target_sentence_length + profile.sentence_length_tolerance)
            limits.append(
                (
                    observed,
                    f"l'empremta de l'autor, que escriu frases d'unes "
                    f"{profile.target_sentence_length:.0f} paraules",
                )
            )
        if not limits and self.preferred_sentence_length is not None:
            preferred = int(self.preferred_sentence_length * LENGTH_MARGIN)
            limits.append(
                (
                    preferred,
                    f"la longitud preferida de {self.preferred_sentence_length} paraules "
                    f"amb un marge",
                )
            )
        if not limits:
            return None, ""
        return min(limits)

    def length_allows(self, words: int, description: str = "") -> bool:
        """Cert si una frase de ``words`` paraules encaixa amb l'estil de l'autor.

        Si no hi encaixa, ho deixa apuntat a ``notes`` perquè el resultat ho
        pugui explicar.
        """
        limit, origin = self.length_limit()
        if limit is None or words <= limit:
            return True
        subject = description or "la frase resultant"
        self.note(
            f"no s'ha fusionat {subject}: tindria {words} paraules i el límit és "
            f"{limit} segons {origin}"
        )
        return False

    def parse(self) -> SentenceSyntax:
        """Anàlisi sintàctica del paràgraf (buida si no hi ha parser instal·lat)."""
        return self.syntax.parse(self.text)

    def parse_sentence(self, sentence: Sentence) -> SentenceSyntax:
        """Anàlisi d'una frase concreta del paràgraf.

        Les regles entre frases han de mirar cada frase per separat: analitzar
        el paràgraf sencer donaria sempre diverses arrels i, per tant, una
        anàlisi poc fiable.
        """
        return self.syntax.parse(sentence.text)

    def syntax_confident(self, *sentences: Sentence) -> bool:
        """Cert si el parser no hi és (i decideixen les heurístiques) o se'n refia.

        Sense parser instal·lat es manté el comportament de sempre; amb parser,
        una frase que no supera el criteri de confiança no autoritza cap
        transformació estructural.
        """
        if not self.syntax.available:
            return True
        return all(self.parse_sentence(s).confident for s in sentences)

    def overlapping_protected(self, span: Span) -> tuple[ProtectedSpan, ...]:
        return tuple(p for p in self.protected_spans if p.overlaps(span))

    def is_protected(self, span: Span) -> bool:
        return any(p.overlaps(span) for p in self.protected_spans)

    def protected_conflict(self, span: Span, text_after: str) -> str | None:
        return protected_conflict(self.text, self.protected_spans, span, text_after)


class _RuleBase:
    def __init__(
        self,
        rule_id: str,
        *,
        transformation_type: TransformationType,
        description: str = "",
        category: str = "",
        level: int = 1,
    ) -> None:
        if not rule_id:
            raise ValueError("Una regla necessita un identificador")
        self._rule_id = rule_id
        self._transformation_type = transformation_type
        self._description = description
        self._category = category
        self._level = level

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def transformation_type(self) -> TransformationType:
        return self._transformation_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def category(self) -> str:
        return self._category

    @property
    def level(self) -> int:
        """Nivell: 1 lèxic, 2 connectors, 3 sintaxi, 4 entre frases, 5 paràgraf."""
        return self._level

    def __repr__(self) -> str:
        return f"{type(self).__name__}(rule_id={self._rule_id!r})"


class Rule(_RuleBase, ABC):
    """Una regla de frase proposa transformacions sobre una frase; mai no les aplica.

    Contracte:

    - Cada transformació proposada ha de ser aplicable a ``ctx.text``.
    - Cap transformació no pot alterar un fragment protegit: pot contenir-lo
      sencer (reordenació) però ha de conservar-lo intacte
      (vegeu :meth:`RuleContext.protected_conflict`).
    - Cada transformació ha de portar una explicació en llenguatge natural.
    """

    @abstractmethod
    def propose(self, ctx: RuleContext) -> Iterable[Transformation]:
        """Retorna les transformacions que la regla proposa per a la frase."""


class ParagraphRule(_RuleBase, ABC):
    """Una regla de paràgraf proposa transformacions que abasten més d'una frase."""

    @abstractmethod
    def propose(self, ctx: ParagraphContext) -> Iterable[Transformation]:
        """Retorna les transformacions proposades sobre el text del paràgraf."""


AnyRule = Rule | ParagraphRule
