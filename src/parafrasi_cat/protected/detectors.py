"""Detectors de fragments protegits.

Tots els detectors treballen sobre el text sencer del document i retornen
intervals absoluts. Són heurístics i deliberadament conservadors: és
preferible protegir de més que de menys, perquè un fragment protegit
innecessàriament només redueix les possibilitats de parafraseig, mentre que
un fragment desprotegit podria acabar alterat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from parafrasi_cat.analyzer.analysis import Analyzer, RuleBasedAnalyzer
from parafrasi_cat.analyzer.clitics import DEFAULT_AUXILIARY_FORMS
from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, WordClass
from parafrasi_cat.analyzer.numerals import ROMAN_CORE, context_allows_single_letter
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import LETTER, phrase_pattern
from parafrasi_cat.protected.spans import ProtectedSpan, ProtectionKind


@runtime_checkable
class Detector(Protocol):
    """Component que localitza fragments a protegir dins d'un text."""

    @property
    def detector_id(self) -> str: ...

    @property
    def kind(self) -> ProtectionKind: ...

    def detect(self, text: str) -> Iterable[ProtectedSpan]: ...


class RegexDetector:
    """Detector genèric basat en una o més expressions regulars."""

    def __init__(
        self,
        detector_id: str,
        kind: ProtectionKind,
        patterns: Sequence[str | re.Pattern[str]],
        *,
        flags: int = 0,
    ) -> None:
        self._detector_id = detector_id
        self._kind = kind
        self._patterns = tuple(re.compile(p, flags) if isinstance(p, str) else p for p in patterns)

    @property
    def detector_id(self) -> str:
        return self._detector_id

    @property
    def kind(self) -> ProtectionKind:
        return self._kind

    @property
    def patterns(self) -> tuple[re.Pattern[str], ...]:
        return self._patterns

    def detect(self, text: str) -> Iterable[ProtectedSpan]:
        spans: list[ProtectedSpan] = []
        for pattern in self._patterns:
            for match in pattern.finditer(text):
                if match.end() > match.start() and self.accept(text, match):
                    spans.append(
                        ProtectedSpan(
                            Span(match.start(), match.end()),
                            match.group(0),
                            self._kind,
                            self._detector_id,
                        )
                    )
        spans.sort(key=lambda p: (p.start, -p.end))
        # Un mateix detector pot trobar un fragment dins d'un altre («març de 2021»
        # dins de «12 de març de 2021»): només es conserva el més ampli.
        kept: list[ProtectedSpan] = []
        for protected in spans:
            if kept and kept[-1].span.contains(protected.span):
                continue
            kept.append(protected)
        return kept

    def accept(self, text: str, match: re.Match[str]) -> bool:
        """Ganxo per descartar coincidències segons el context. Per defecte accepta tot."""
        return True


_MONTHS = "gener|febrer|març|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre"
_ERA = r"(?:aC|dC|a\.\s?C\.|d\.\s?C\.|abans de Crist|després de Crist)"


class DateDetector(RegexDetector):
    """Dates numèriques (12/03/2021, 2021-03-12), textuals (12 de març de 2021) i eres (218 aC)."""

    def __init__(self) -> None:
        super().__init__(
            "date.regex",
            ProtectionKind.DATE,
            [
                r"\b\d{4}-\d{2}-\d{2}\b",
                r"\b\d{4}/\d{1,2}/\d{1,2}\b",
                r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b",
                rf"\b\d{{1,2}}\s+(?:de\s+|d['’])(?:{_MONTHS})(?:\s+(?:de|del)\s+\d{{4}})?\b",
                rf"\b(?:{_MONTHS})\s+(?:de|del)\s+\d{{4}}\b",
                rf"\b\d{{1,4}}\s?{_ERA}(?!{LETTER})",
                rf"\bsegle\s+[IVXLCDM]+\s?{_ERA}(?!{LETTER})",
            ],
            flags=re.IGNORECASE,
        )


class NumberDetector(RegexDetector):
    """Xifres: enters, decimals, hores (10:30), percentatges, imports i ordinals (3r, 5è)."""

    def __init__(self) -> None:
        super().__init__(
            "number.regex",
            ProtectionKind.NUMBER,
            [r"(?<![\w.,])[+\-−]?\d+(?:[.,]\d+)*(?::\d{2})?(?:[a-zè]{1,3})?(?:\s?[%€$])?(?!\w)"],
        )


class RomanNumeralDetector(RegexDetector):
    """Números romans en majúscules (XX, XIV, MCMXCII, XXIè).

    Una sola lletra (I, V, X, L, C, D, M) només es considera numeral si va
    precedida d'una paraula de context («segle X») o d'un nom propi
    («Jaume I»); vegeu :mod:`parafrasi_cat.analyzer.numerals`.
    """

    def __init__(self) -> None:
        super().__init__(
            "roman_numeral.regex",
            ProtectionKind.ROMAN_NUMERAL,
            [rf"(?<!{LETTER})(?=[MDCLXVI])(?:{ROMAN_CORE})(?:è)?(?!{LETTER})"],
        )

    def accept(self, text: str, match: re.Match[str]) -> bool:
        numeral = match.group(0).rstrip("è")
        if len(numeral) > 1:
            return True
        return context_allows_single_letter(text[: match.start()])


class QuotedTextDetector(RegexDetector):
    """Text entre cometes baixes «», altes “”, rectes dobles "" i simples ‘’."""

    def __init__(self) -> None:
        super().__init__(
            "quoted_text.regex",
            ProtectionKind.QUOTED_TEXT,
            [r"«[^«»]*»", r"“[^“”]*”", r"\"[^\"\n]*\"", r"‘[^‘’\n]*’"],
        )


class CitationDetector(RegexDetector):
    """Referències bibliogràfiques: (Autor, 2001), [12], p. 34, ibid., op. cit., et al."""

    def __init__(self) -> None:
        super().__init__(
            "citation.regex",
            ProtectionKind.CITATION,
            [
                r"\([^()\n]*?\b(?:1[0-9]{3}|20[0-9]{2})[a-z]?\b[^()\n]*\)",
                r"\[\d+(?:\s?[,;–\-]\s?\d+)*\]",
                rf"(?<!{LETTER})(?:pp?|pàgs?|fols?|ff)\.\s?\d+(?:\s?[–\-]\s?\d+)?",
                rf"(?<!{LETTER})(?:ibid|ibíd|íd|op\.\s?cit|loc\.\s?cit|et\s+al)\.",
                rf"(?<!{LETTER})(?:vol|núm|n|cap|llibre|tom)\.\s?(?:[IVXLCDM]+|\d+)(?!{LETTER})",
            ],
            flags=re.IGNORECASE,
        )


class UserTermDetector:
    """Termes definits per l'usuari (terminologia protegida, noms coneguts)."""

    def __init__(
        self,
        terms: Iterable[str],
        *,
        detector_id: str = "user_term.list",
        kind: ProtectionKind = ProtectionKind.USER_TERM,
        ignore_case: bool = True,
    ) -> None:
        self._detector_id = detector_id
        self._kind = kind
        self._terms = tuple(dict.fromkeys(t.strip() for t in terms if t.strip()))
        self._patterns = tuple(
            (term, phrase_pattern(term, ignore_case=ignore_case)) for term in self._terms
        )

    @property
    def detector_id(self) -> str:
        return self._detector_id

    @property
    def kind(self) -> ProtectionKind:
        return self._kind

    @property
    def terms(self) -> tuple[str, ...]:
        return self._terms

    def detect(self, text: str) -> Iterable[ProtectedSpan]:
        for term, pattern in self._patterns:
            for match in pattern.finditer(text):
                yield ProtectedSpan(
                    Span(match.start(), match.end()),
                    match.group(0),
                    self._kind,
                    self._detector_id,
                    note=term,
                )


#: Mots de lligam que poden aparèixer dins d'un nom propi compost
#: («Universitat de Barcelona», «Institut d'Estudis Catalans», «Fabra i Poch»),
#: amb les partícules dels noms estrangers («Benedetto da Rovezzano», «Ludwig
#: van Beethoven», «Leonardo di Caprio»): sense elles, la partícula quedaria
#: fora del fragment protegit i alguna regla la podria prendre per un mot corrent.
_NAME_CONNECTORS: frozenset[str] = frozenset(
    {"de", "del", "dels", "d'", "d’", "la", "les", "el", "els", "i", "l'", "l’", "en", "na",
     "da", "di", "du", "von", "van", "der", "den", "della", "delle", "dei", "degli", "do",
     "dos", "das", "le", "des"}
)  # fmt: skip

#: Connectors admesos just després de la primera paraula d'una frase
#: («Universitat de Barcelona és...», «Consell d'Europa...»).
_DE_CONNECTORS: frozenset[str] = frozenset({"de", "del", "dels", "d'", "d’"})

#: Articles admesos després de la primera paraula d'una frase només quan
#: aquesta no sembla un verb («Guifré el Pilós», «Martí l'Humà», però no
#: «Visitem el Museu»).
_ARTICLE_CONNECTORS: frozenset[str] = frozenset({"el", "la", "l'", "l’"})

#: Mots gramaticals que, en majúscula al començament de frase, no formen part
#: d'un nom propi («La Universitat de Barcelona» → «Universitat de Barcelona»).
#: El lexicó de classes tancades amplia aquesta llista.
_SENTENCE_START_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "el",
        "la",
        "els",
        "les",
        "l'",
        "l’",
        "un",
        "una",
        "uns",
        "unes",
        "a",
        "al",
        "als",
        "de",
        "del",
        "dels",
        "d'",
        "d’",
        "en",
        "per",
        "amb",
        "i",
        "o",
        "que",
        "què",
        "com",
        "quan",
        "on",
        "si",
        "no",
        "hi",
        "ho",
        "es",
        "s'",
        "s’",
        "aquest",
        "aquesta",
        "aquests",
        "aquestes",
        "aquell",
        "aquella",
        "aquells",
        "aquelles",
        "tot",
        "tots",
        "tota",
        "totes",
        "cap",
        "cada",
        "molts",
        "moltes",
        "alguns",
        "algunes",
        "segons",
        "durant",
        "sobre",
        "sota",
        "des",
        "fins",
        "entre",
        "sense",
        "però",
        "doncs",
        "també",
        "només",
        "ja",
        "ara",
        "avui",
        "ahir",
        "demà",
        "després",
        "abans",
        "quant",
        "quants",
        "quantes",
    }
)

_VERB_LIKE_ENDING_RE = re.compile(r"(?:em|eu|im|iu)$")


class ProperNounDetector:
    """Noms propis detectats per heurística de majúscules.

    - Una paraula amb majúscula inicial enmig d'una frase es considera nom propi.
    - Al començament de frase, només si forma part d'una seqüència de dues o més
      paraules amb majúscula («Joan Maragall va...») o si és una sigla. Els mots
      gramaticals inicials («La», «El», «Segons», «Se»...) no compten.
    - Les seqüències es poden encadenar amb mots de lligam («Generalitat de
      Catalunya», «Fabra i Poch», «Ramon Berenguer IV», «Guifré el Pilós»). Una
      enumeració com «Madrid i València» queda protegida com un sol fragment,
      cosa que és segura tot i ser imprecisa.
    - Un número romà no pot començar un nom, però sí continuar-lo («Borrell II»).

    És una heurística: els noms coneguts es poden afegir al diccionari
    ``dictionaries/noms_propis.txt`` per garantir-ne la protecció.
    """

    detector_id = "proper_noun.heuristic"
    kind = ProtectionKind.PROPER_NOUN

    def __init__(
        self,
        analyzer: Analyzer | None = None,
        *,
        max_connectors: int = 2,
        lexicon: ClosedClassLexicon | None = None,
    ) -> None:
        self._analyzer = analyzer or RuleBasedAnalyzer()
        self._max_connectors = max_connectors
        skip = set(_SENTENCE_START_FUNCTION_WORDS)
        auxiliaries: frozenset[str] = DEFAULT_AUXILIARY_FORMS
        if lexicon is not None:
            skip |= lexicon.single_word_forms
            auxiliaries = lexicon.forms_of(WordClass.AUXILIARY) or auxiliaries
        self._skip_initial = frozenset(skip)
        self._auxiliaries = auxiliaries

    def detect(self, text: str) -> Iterable[ProtectedSpan]:
        for sentence in self._analyzer.analyze(text).sentences:
            yield from self._detect_in_sentence(sentence)

    def _detect_in_sentence(self, sentence: Sentence) -> Iterable[ProtectedSpan]:
        words = [t for t in sentence.tokens if t.is_word]
        i = 0
        while i < len(words):
            at_sentence_start = i == 0
            if not self._can_start(words[i], at_sentence_start):
                i += 1
                continue
            run_end = self._extend_run(sentence.text, words, i, strict_first=at_sentence_start)
            n_words = run_end - i + 1
            first = words[i]
            if not at_sentence_start or n_words >= 2 or _is_acronym(first.text):
                span = Span(first.span.start, words[run_end].span.end)
                yield ProtectedSpan(
                    sentence.absolute(span),
                    span.slice(sentence.text),
                    self.kind,
                    self.detector_id,
                )
            i = run_end + 1

    def _can_start(self, token: Token, at_sentence_start: bool) -> bool:
        if not _is_capitalized(token.text) or token.kind is TokenKind.CLITIC:
            return False
        if token.subkind is TokenSubkind.ROMAN_NUMERAL:
            return False
        return not (at_sentence_start and token.lower.replace("’", "'") in self._skip_initial)

    def _verb_like(self, word: str) -> bool:
        lowered = word.lower()
        if lowered in self._auxiliaries:
            return True
        return len(lowered) >= 4 and _VERB_LIKE_ENDING_RE.search(lowered) is not None

    def _extend_run(
        self, text: str, words: list[Token], start: int, *, strict_first: bool = False
    ) -> int:
        """Retorna l'índex de l'última paraula de la seqüència que comença a ``start``.

        Amb ``strict_first`` (començament de frase), el primer enllaç només pot
        ser una paraula amb majúscula, un connector de tipus «de» o, si el mot
        inicial no sembla un verb, un article: així «Visitem l'Institut» no
        arrossega el verb dins del nom, però «Guifré el Pilós» queda sencer.
        """
        first_allowed = _NAME_CONNECTORS
        if strict_first:
            first_allowed = _DE_CONNECTORS
            if not self._verb_like(words[start].text):
                first_allowed = _DE_CONNECTORS | _ARTICLE_CONNECTORS
        run_end = start
        j = start + 1
        while j < len(words):
            if _is_capitalized(words[j].text) and _only_space_between(text, words[j - 1], words[j]):
                run_end = j
                j += 1
                continue
            allowed = first_allowed if j == start + 1 else _NAME_CONNECTORS
            k = j
            while (
                k < len(words)
                and k - j < self._max_connectors
                and words[k].lower in (allowed if k == j else _NAME_CONNECTORS)
                and _only_space_between(text, words[k - 1], words[k])
            ):
                k += 1
            if (
                k > j
                and k < len(words)
                and _is_capitalized(words[k].text)
                and words[k].kind is not TokenKind.CLITIC
                and _only_space_between(text, words[k - 1], words[k])
            ):
                run_end = k
                j = k + 1
                continue
            break
        return run_end


def _is_capitalized(word: str) -> bool:
    return bool(word) and word[0].isupper()


def _is_acronym(word: str) -> bool:
    letters = [c for c in word if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def _only_space_between(text: str, left: Token, right: Token) -> bool:
    between = text[left.span.end : right.span.start]
    return between == "" or between.isspace()
