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
from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.analyzer.tokens import Token
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


class DateDetector(RegexDetector):
    """Dates numèriques (12/03/2021, 2021-03-12) i textuals (12 de març de 2021)."""

    def __init__(self) -> None:
        super().__init__(
            "date.regex",
            ProtectionKind.DATE,
            [
                r"\b\d{4}-\d{2}-\d{2}\b",
                r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b",
                rf"\b\d{{1,2}}\s+(?:de\s+|d['’])(?:{_MONTHS})(?:\s+(?:de|del)\s+\d{{4}})?\b",
                rf"\b(?:{_MONTHS})\s+(?:de|del)\s+\d{{4}}\b",
            ],
            flags=re.IGNORECASE,
        )


class NumberDetector(RegexDetector):
    """Xifres (enters, decimals, percentatges, imports, ordinals numèrics)."""

    def __init__(self) -> None:
        super().__init__(
            "number.regex",
            ProtectionKind.NUMBER,
            [r"(?<![\w.,])[+\-−]?\d+(?:[.,]\d+)*(?:[a-zè]{1,2})?(?:\s?[%€$])?(?!\w)"],
        )


_ROMAN_CORE = r"M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"

#: Paraules que, immediatament abans d'una sola lletra romana (I, V, X...),
#: confirmen que es tracta d'un numeral: «segle X», «Jaume I», «capítol V».
_ROMAN_CONTEXT_WORDS: frozenset[str] = frozenset(
    {
        "segle",
        "segles",
        "s",
        "ss",
        "capítol",
        "capítols",
        "cap",
        "volum",
        "volums",
        "vol",
        "tom",
        "toms",
        "part",
        "parts",
        "llibre",
        "llibres",
        "acte",
        "actes",
        "escena",
        "escenes",
        "títol",
        "títols",
        "annex",
        "annexos",
        "article",
        "articles",
        "art",
        "secció",
        "seccions",
        "apartat",
        "apartats",
        "papa",
        "rei",
        "reina",
        "emperador",
        "emperadriu",
        "comte",
        "comtessa",
        "duc",
        "duquessa",
        "fase",
        "fases",
        "nivell",
        "nivells",
        "grau",
        "graus",
        "classe",
        "tipus",
        "categoria",
        "fitxa",
        "lliçó",
        "lliçons",
        "unitat",
        "unitats",
        "quadre",
        "quadres",
        "taula",
        "taules",
        "figura",
        "figures",
        "mapa",
        "mapes",
        "làmina",
        "làmines",
        "cant",
        "cants",
    }
)

_WORD_BEFORE_RE = re.compile(rf"({LETTER}+(?:[·\-']{LETTER}+)*)\.?\s*$")


class RomanNumeralDetector(RegexDetector):
    """Números romans en majúscules (XX, XIV, MCMXCII).

    Una sola lletra (I, V, X, L, C, D, M) només es considera numeral si va
    precedida d'una paraula de context («segle X») o d'un nom propi
    («Jaume I»), per evitar confondre-la amb la conjunció «I» o amb sigles.
    """

    def __init__(self) -> None:
        super().__init__(
            "roman_numeral.regex",
            ProtectionKind.ROMAN_NUMERAL,
            [rf"(?<!{LETTER})(?=[MDCLXVI])(?:{_ROMAN_CORE})(?!{LETTER})"],
        )

    def accept(self, text: str, match: re.Match[str]) -> bool:
        numeral = match.group(0)
        if len(numeral) > 1:
            return True
        before = _WORD_BEFORE_RE.search(text, 0, match.start())
        if before is None:
            return False
        word = before.group(1)
        return word.lower() in _ROMAN_CONTEXT_WORDS or word[0].isupper()


class QuotedTextDetector(RegexDetector):
    """Text entre cometes baixes «», altes “” i rectes dobles ""."""

    def __init__(self) -> None:
        super().__init__(
            "quoted_text.regex",
            ProtectionKind.QUOTED_TEXT,
            [r"«[^«»]*»", r"“[^“”]*”", r"\"[^\"\n]*\"", r"‘[^‘’\n]*’"],
        )


class CitationDetector(RegexDetector):
    """Referències bibliogràfiques: (Autor, 2001), [12], p. 34, ibid., op. cit."""

    def __init__(self) -> None:
        super().__init__(
            "citation.regex",
            ProtectionKind.CITATION,
            [
                r"\([^()\n]*?\b(?:1[0-9]{3}|20[0-9]{2})[a-z]?\b[^()\n]*\)",
                r"\[\d+(?:\s?[,;–\-]\s?\d+)*\]",
                rf"(?<!{LETTER})(?:pp?|pàgs?)\.\s?\d+(?:\s?[–\-]\s?\d+)?",
                rf"(?<!{LETTER})(?:ibid|ibíd|íd|op\.\s?cit|loc\.\s?cit)\.",
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
#: («Universitat de Barcelona», «Institut d'Estudis Catalans», «Fabra i Poch»).
_NAME_CONNECTORS: frozenset[str] = frozenset(
    {"de", "del", "dels", "d'", "d’", "la", "les", "el", "els", "i", "l'", "l’", "en", "na"}
)

#: Connectors admesos just després de la primera paraula d'una frase
#: («Universitat de Barcelona és...», «Consell d'Europa...»).
_DE_CONNECTORS: frozenset[str] = frozenset({"de", "del", "dels", "d'", "d’"})

#: Mots gramaticals que, en majúscula al començament de frase, no formen part
#: d'un nom propi («La Universitat de Barcelona» → «Universitat de Barcelona»).
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


class ProperNounDetector:
    """Noms propis detectats per heurística de majúscules.

    - Una paraula amb majúscula inicial enmig d'una frase es considera nom propi.
    - Al començament de frase, només si forma part d'una seqüència de dues o més
      paraules amb majúscula («Joan Maragall va...») o si és una sigla. Els mots
      gramaticals inicials («La», «El», «Segons»...) no compten.
    - Les seqüències es poden encadenar amb mots de lligam («Generalitat de
      Catalunya», «Fabra i Poch»). Una enumeració com «Madrid i València» queda
      protegida com un sol fragment, cosa que és segura tot i ser imprecisa.

    És una heurística: els noms coneguts es poden afegir al diccionari
    ``dictionaries/noms_propis.txt`` per garantir-ne la protecció.
    """

    detector_id = "proper_noun.heuristic"
    kind = ProtectionKind.PROPER_NOUN

    def __init__(self, analyzer: Analyzer | None = None, *, max_connectors: int = 2) -> None:
        self._analyzer = analyzer or RuleBasedAnalyzer()
        self._max_connectors = max_connectors

    def detect(self, text: str) -> Iterable[ProtectedSpan]:
        for sentence in self._analyzer.analyze(text).sentences:
            yield from self._detect_in_sentence(sentence)

    def _detect_in_sentence(self, sentence: Sentence) -> Iterable[ProtectedSpan]:
        words = [t for t in sentence.tokens if t.is_word]
        i = 0
        while i < len(words):
            if not _is_capitalized(words[i].text):
                i += 1
                continue
            if i == 0 and words[0].text.lower() in _SENTENCE_START_FUNCTION_WORDS:
                i += 1
                continue
            at_sentence_start = i == 0
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

    def _extend_run(
        self, text: str, words: list[Token], start: int, *, strict_first: bool = False
    ) -> int:
        """Retorna l'índex de l'última paraula de la seqüència que comença a ``start``.

        Amb ``strict_first`` (començament de frase), el primer enllaç només pot
        ser una paraula amb majúscula o un connector de tipus «de»: així
        «Visitem l'Institut» no arrossega el verb inicial dins del nom.
        """
        run_end = start
        j = start + 1
        while j < len(words):
            if _is_capitalized(words[j].text) and _only_space_between(text, words[j - 1], words[j]):
                run_end = j
                j += 1
                continue
            allowed = _DE_CONNECTORS if strict_first and j == start + 1 else _NAME_CONNECTORS
            k = j
            while (
                k < len(words)
                and k - j < self._max_connectors
                and words[k].text.lower() in (allowed if k == j else _NAME_CONNECTORS)
                and _only_space_between(text, words[k - 1], words[k])
            ):
                k += 1
            if (
                k > j
                and k < len(words)
                and _is_capitalized(words[k].text)
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
