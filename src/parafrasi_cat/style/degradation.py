"""Degradació estructural local d'un candidat respecte de l'original.

Una transformació pot ser gramatical i, tot i així, empitjorar la frase:
convertir un participi en relativa al costat d'una altra relativa dona «que
fou impulsada..., que intensificà...», dues relatives consecutives amb el
mateix marcador. Aquí es mesura, de manera general i comparant sempre el
candidat amb l'original, si el canvi introdueix:

- **relatives consecutives**: dues relatives seguides dins de la mateixa frase
  (la segona comença poc després de la primera);
- **acumulació de «que»**: més subordinants «que» dels que tenia l'original;
- **repetició d'estructura**: la mateixa seqüència «marcador + mot» repetida
  dins d'una frase («que fou ..., que fou ...»).

El resultat és un grau de degradació entre 0 i 1 que la puntuació aplica com a
penalització, mai com a invalidació: la regla continua sent útil en altres
contextos. Si l'empremta de l'autor mostra que ell mateix encadena
subordinades sovint (profunditat de subordinació 2 o més), la penalització
es rebaixa proporcionalment.

Amb analitzador sintàctic es distingeix el «que» relatiu del completiu quan
el parser en dona el tipus de pronom; sense analitzador, o quan l'anàlisi no
és fiable, només compta com a relativa el «que» precedit de coma (la relativa
explicativa, que és la que s'encadena).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import Token, TokenKind
from parafrasi_cat.style.preferences import StylePreferences
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxProvider

#: Marcadors que obren una relativa quan van precedits de coma.
RELATIVE_MARKERS: frozenset[str] = frozenset(
    {"que", "qui", "on", "el qual", "la qual", "els quals", "les quals", "què"}
)
#: Distància màxima (en mots) entre dues relatives perquè comptin com a consecutives.
CHAIN_WINDOW = 15
#: Pes de cada senyal en el grau de degradació.
CHAIN_PENALTY = 0.8
QUE_PENALTY = 0.2
REPEAT_PENALTY = 0.2
#: Rebaixa màxima de la penalització per a un autor que encadena subordinades.
MAX_TOLERANCE_DISCOUNT = 0.5


@dataclass(frozen=True, slots=True)
class SentenceShape:
    """Recomptes estructurals d'una frase que serveixen per comparar-la amb l'original."""

    relatives: int = 0
    chains: int = 0
    que: int = 0
    repeated: int = 0

    def __add__(self, other: SentenceShape) -> SentenceShape:
        return SentenceShape(
            self.relatives + other.relatives,
            self.chains + other.chains,
            self.que + other.que,
            self.repeated + other.repeated,
        )


@dataclass(frozen=True, slots=True)
class DegradationAssessment:
    """Grau de degradació (0-1) i els motius, en català."""

    score: float = 0.0
    reasons: tuple[str, ...] = ()
    candidate: SentenceShape = field(default_factory=SentenceShape)
    source: SentenceShape = field(default_factory=SentenceShape)

    @property
    def degraded(self) -> bool:
        return self.score > 0

    def to_dict(self) -> dict[str, object]:
        return {"score": self.score, "reasons": list(self.reasons)}


class StructuralDegradation:
    """Mesura la degradació estructural local d'un text respecte del que substitueix."""

    def __init__(
        self,
        analyzer: Analyzer,
        syntax: SyntaxProvider | None = None,
        preferences: StylePreferences | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._syntax = syntax if syntax is not None and syntax.available else None
        self._tolerance = _author_tolerance(preferences)
        self._cache: dict[str, SentenceShape] = {}

    @property
    def tolerance(self) -> float:
        """Proporció (0-1) de frases de l'autor amb subordinació encadenada, si se sap."""
        return self._tolerance

    def shape_of(self, text: str) -> SentenceShape:
        """Recomptes estructurals d'un text (suma de les seves frases), amb memòria cau."""
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        total = SentenceShape()
        for sentence in self._analyzer.analyze(text).sentences:
            parsed = self._syntax.parse(sentence.text) if self._syntax is not None else None
            total = total + sentence_shape(sentence, parsed)
        self._cache[text] = total
        return total

    def assess(self, text: str, source_text: str) -> DegradationAssessment:
        """Degradació de ``text`` respecte de ``source_text`` (0 si no n'introdueix cap)."""
        if text == source_text:
            return DegradationAssessment()
        candidate = self.shape_of(text)
        source = self.shape_of(source_text)
        reasons: list[str] = []
        raw = 0.0
        new_chains = max(0, candidate.chains - source.chains)
        if new_chains:
            raw += CHAIN_PENALTY * new_chains
            reasons.append(
                "introdueix relatives consecutives amb el mateix marcador («..., que ..., que ...»)"
            )
        extra_que = max(0, candidate.que - source.que)
        if extra_que:
            raw += QUE_PENALTY * extra_que
            reasons.append(f"afegeix {extra_que} subordinant{'s' if extra_que > 1 else ''} «que»")
        new_repeats = max(0, candidate.repeated - source.repeated)
        if new_repeats:
            raw += REPEAT_PENALTY * new_repeats
            reasons.append("repeteix la mateixa estructura subordinada dins d'una frase")
        if raw <= 0:
            return DegradationAssessment(0.0, (), candidate, source)
        discount = MAX_TOLERANCE_DISCOUNT * self._tolerance
        if discount:
            reasons.append(
                f"penalització rebaixada: l'autor encadena subordinades ({self._tolerance:.0%})"
            )
        score = round(min(1.0, raw) * (1.0 - discount), 4)
        return DegradationAssessment(score, tuple(reasons), candidate, source)


def sentence_shape(sentence: Sentence, parsed: SentenceSyntax | None = None) -> SentenceShape:
    """Relatives, cadenes de relatives, «que» i estructures repetides d'una frase."""
    tokens = [t for t in sentence.tokens if t.kind is not TokenKind.SPACE]
    relatives: list[int] = []
    que = 0
    bigrams: dict[str, int] = {}
    words = [t for t in tokens if t.is_word]
    for position, token in enumerate(tokens):
        low = token.lower.replace("’", "'")
        if low == "que":
            que += 1
        if not _is_relative(tokens, position, parsed):
            continue
        relatives.append(_word_position(words, token))
        following = _next_word(tokens, position)
        if following is not None:
            key = f"{low} {following.lower}"
            bigrams[key] = bigrams.get(key, 0) + 1
    chains = sum(
        1
        for first, second in zip(relatives, relatives[1:], strict=False)
        if second - first <= CHAIN_WINDOW
    )
    repeated = sum(count - 1 for count in bigrams.values() if count > 1)
    return SentenceShape(len(relatives), chains, que, repeated)


def _is_relative(tokens: Sequence[Token], position: int, parsed: SentenceSyntax | None) -> bool:
    token = tokens[position]
    low = token.lower.replace("’", "'")
    if low not in RELATIVE_MARKERS or not token.is_word:
        return False
    previous = tokens[position - 1] if position > 0 else None
    if previous is not None and previous.kind is TokenKind.PUNCT and previous.text == ",":
        return True
    if parsed is not None and parsed.confident:
        analysed = parsed.token_at(token.span.start)
        if analysed is not None and analysed.end == token.span.end:
            return analysed.pron_type == "Rel" or analysed.dep == "acl:relcl"
    return False


def _word_position(words: Sequence[Token], token: Token) -> int:
    for position, word in enumerate(words):
        if word.span.start == token.span.start:
            return position
    return 0


def _next_word(tokens: Sequence[Token], position: int) -> Token | None:
    for token in tokens[position + 1 :]:
        if token.is_word:
            return token
        if token.kind is TokenKind.PUNCT:
            return None
    return None


def _author_tolerance(preferences: StylePreferences | None) -> float:
    """Proporció de frases de l'autor amb subordinació de profunditat 2 o més."""
    if preferences is None:
        return 0.0
    profile = preferences.fingerprint.get("syntactic_profile")
    if not isinstance(profile, Mapping) or profile.get("confidence") == "low":
        return 0.0
    subordination = profile.get("subordination")
    if not isinstance(subordination, Mapping):
        return 0.0
    distribution = subordination.get("depth_distribution")
    if not isinstance(distribution, Mapping):
        return 0.0
    deep = 0.0
    for key, value in distribution.items():
        if str(key) in ("0", "1") or isinstance(value, bool) or not isinstance(value, int | float):
            continue
        deep += float(value)
    return max(0.0, min(1.0, deep))


__all__ = [
    "CHAIN_WINDOW",
    "DegradationAssessment",
    "SentenceShape",
    "StructuralDegradation",
    "sentence_shape",
]
