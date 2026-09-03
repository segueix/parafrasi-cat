"""Tokenització basada en regles per al català.

El tokenitzador treballa en dues passades:

1. Una expressió regular localitza «trossos» màxims: nombres (amb ordinals),
   seqüències de lletres (amb apòstrofs, guionets i punts volats interns),
   espais i signes de puntuació.
2. Cada tros de lletres es descompon segons la morfologia del català:
   proclítics elidits al davant (l', d', s', m', n', t'), pronoms enclítics
   al darrere (-ho, -la, 'n, -me'n, -m'ho, -nos-en...) i mots compostos amb
   guionet (sud-oest, pèl-roig). Els signes de puntuació reben una
   subcategoria (final de frase, pausa, cometa d'obertura...).

Totes les posicions es conserven exactament respecte del text d'entrada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.text import APOSTROPHES, LETTER


class TokenKind(StrEnum):
    WORD = "word"
    """Paraula ordinària (inclou mots amb guionet i amb ela geminada)."""

    CLITIC = "clitic"
    """Article o pronom elidit (l', d', s'...) o pronom enclític ('n, -ho, -me'n...)."""

    NUMBER = "number"
    PUNCT = "punct"
    SPACE = "space"
    OTHER = "other"


class TokenSubkind(StrEnum):
    """Subcategoria d'un token, quan la forma permet determinar-la."""

    # Clítics
    PROCLITIC = "proclitic"
    """Forma elidida davant d'un mot que comença en vocal: l', d', s', m', n', t'."""

    ENCLITIC = "enclitic"
    """Pronom feble darrere d'un verb: -ho, -la, 'n, -me'n, -m'ho, -nos-en..."""

    # Paraules
    COMPOUND = "compound"
    """Mot compost amb guionet no pronominal: sud-oest, pèl-roig, Vila-seca."""

    ABBREVIATION = "abbreviation"
    """Abreviatura seguida de punt: Sr., pàg., cf., et al."""

    ROMAN_NUMERAL = "roman_numeral"
    """Número romà: XI, XIII, MCMXCII (també ordinal: XXIè)."""

    # Nombres
    ORDINAL = "ordinal"
    """Ordinal en xifres: 1r, 2n, 3a, 4t, 5è, 2ns."""

    # Puntuació
    SENTENCE_END = "sentence_end"
    PAUSE = "pause"
    QUOTE_OPEN = "quote_open"
    QUOTE_CLOSE = "quote_close"
    BRACKET_OPEN = "bracket_open"
    BRACKET_CLOSE = "bracket_close"
    DASH = "dash"
    HYPHEN = "hyphen"
    APOSTROPHE = "apostrophe"
    SYMBOL = "symbol"


@dataclass(frozen=True, slots=True)
class Token:
    """Unitat mínima de text amb la seva posició relativa a la frase."""

    text: str
    span: Span
    kind: TokenKind
    subkind: TokenSubkind | None = None

    @property
    def is_word(self) -> bool:
        """Cert per a paraules i clítics (unitats amb contingut lèxic)."""
        return self.kind in (TokenKind.WORD, TokenKind.CLITIC)

    @property
    def is_lexical(self) -> bool:
        """Cert per a paraules, clítics i nombres."""
        return self.is_word or self.kind is TokenKind.NUMBER

    @property
    def is_punct(self) -> bool:
        return self.kind is TokenKind.PUNCT

    @property
    def is_clitic(self) -> bool:
        return self.kind is TokenKind.CLITIC

    @property
    def lower(self) -> str:
        return self.text.lower()

    @property
    def has_hyphen(self) -> bool:
        return "-" in self.text

    @property
    def has_apostrophe(self) -> bool:
        return any(c in APOSTROPHES for c in self.text)

    def with_subkind(self, subkind: TokenSubkind | None) -> Token:
        return replace(self, subkind=subkind)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "span": self.span.to_dict(),
            "kind": self.kind.value,
            "subkind": None if self.subkind is None else self.subkind.value,
        }


# --- Primera passada: trossos màxims -------------------------------------------

_ORDINAL_SUFFIX = r"(?:r|rs|n|ns|t|ts|è|a|es)"

_TOKEN_RE = re.compile(
    rf"""
    (?P<number>\d+(?:[.,]\d+)*(?::\d{{2}})?)(?P<ordinal>{_ORDINAL_SUFFIX}(?!{LETTER}))?
    |(?P<ellipsis>\.{{3}})
    |(?P<chunk>{LETTER}(?:{LETTER}|·|[-'’](?={LETTER}))*['’]?)
    |(?P<space>\s+)
    |(?P<punct>[^\w\s])
    |(?P<other>\w+)
    """,
    re.VERBOSE,
)

# --- Segona passada: descomposició dels trossos de lletres ---------------------

_PROCLITIC_LETTERS = frozenset("ldsmnt")
_PROCLITIC_RE = re.compile(rf"([lLdDsSmMnNtT])(['’])(?={LETTER})")
_SEPARATORS = "-" + APOSTROPHES

# Peces d'una cadena de pronoms enclítics. L'ordre (llargs primer) evita que
# «-lo» capturi el començament de «-los».
_PIECE_HYPHEN_ELIDED_RE = re.compile(r"-([mtsnl])['’](?=(?:ho|hi)(?:$|[-'’]))", re.IGNORECASE)
_PIECE_HYPHEN_FULL_RE = re.compile(
    r"-(nos|vos|los|les|els|me|te|se|lo|la|li|ho|hi|ne|us|en|el)(?=$|[-'’])", re.IGNORECASE
)
_PIECE_APOSTROPHE_RE = re.compile(r"['’](ns|ls|m|t|s|l|n)(?=$|[-'’])", re.IGNORECASE)
_PIECE_BARE_RE = re.compile(r"(ho|hi)(?=$|[-'’])", re.IGNORECASE)

#: Formes amb guionet que només poden aparèixer després d'un altre pronom
#: («anem-nos-en», «porteu-los-el»), mai directament darrere del verb.
_HYPHEN_NONFIRST = frozenset({"en", "el", "els"})


def _parse_enclitic_chain(rest: str) -> list[str] | None:
    """Analitza ``rest`` (que comença per guionet o apòstrof) com a cadena de pronoms.

    Retorna les peces («-me», «'n», «-m'», «ho»...) o ``None`` si ``rest``
    no és una cadena vàlida de pronoms enclítics.
    """
    pieces: list[str] = []
    index = 0
    expect_bare = False
    while index < len(rest):
        segment = rest[index:]
        match: re.Match[str] | None
        if expect_bare:
            match = _PIECE_BARE_RE.match(segment)
            expect_bare = False
        elif segment[0] == "-":
            match = _PIECE_HYPHEN_ELIDED_RE.match(segment)
            if match is not None:
                expect_bare = True
            else:
                match = _PIECE_HYPHEN_FULL_RE.match(segment)
                if match is not None and match.group(1).lower() in _HYPHEN_NONFIRST and not pieces:
                    match = None
        elif segment[0] in APOSTROPHES:
            match = _PIECE_APOSTROPHE_RE.match(segment)
        else:
            match = None
        if match is None:
            return None
        pieces.append(match.group(0))
        index += len(match.group(0))
    if expect_bare:
        return None
    return pieces or None


def split_word_chunk(chunk: str, offset: int = 0) -> list[Token]:
    """Descompon un tros de lletres en proclítics, mot amfitrió i enclítics.

    Exemples: ``l'home`` → «l'» + «home»; ``vés-te'n`` → «vés» + «-te» + «'n»;
    ``dona-m'ho`` → «dona» + «-m'» + «ho»; ``sud-oest`` → «sud-oest» (compost).
    """
    tokens: list[Token] = []
    position = 0
    while True:
        match = _PROCLITIC_RE.match(chunk, position)
        if match is None:
            break
        tokens.append(
            Token(
                match.group(0),
                Span(offset + position, offset + match.end()),
                TokenKind.CLITIC,
                TokenSubkind.PROCLITIC,
            )
        )
        position = match.end()

    body = chunk[position:]
    if not body:
        return tokens

    # «l'» seguit d'una xifra o al final del tros: proclític sense mot al mateix tros.
    if len(body) == 2 and body[0].lower() in _PROCLITIC_LETTERS and body[1] in APOSTROPHES:
        tokens.append(
            Token(
                body,
                Span(offset + position, offset + position + 2),
                TokenKind.CLITIC,
                TokenSubkind.PROCLITIC,
            )
        )
        return tokens

    trailing_apostrophe = ""
    if body[-1] in APOSTROPHES:
        trailing_apostrophe = body[-1]
        body = body[:-1]

    host_end = len(body)
    pieces: list[str] | None = None
    for index, char in enumerate(body):
        if index == 0 or char not in _SEPARATORS:
            continue
        pieces = _parse_enclitic_chain(body[index:])
        if pieces is not None:
            host_end = index
            break

    host = body[:host_end]
    host_start = offset + position
    tokens.append(
        Token(
            host,
            Span(host_start, host_start + len(host)),
            TokenKind.WORD,
            TokenSubkind.COMPOUND if "-" in host else None,
        )
    )
    cursor = host_start + len(host)
    for piece in pieces or ():
        tokens.append(
            Token(piece, Span(cursor, cursor + len(piece)), TokenKind.CLITIC, TokenSubkind.ENCLITIC)
        )
        cursor += len(piece)
    if trailing_apostrophe:
        tokens.append(
            Token(
                trailing_apostrophe,
                Span(cursor, cursor + 1),
                TokenKind.PUNCT,
                TokenSubkind.APOSTROPHE,
            )
        )
    return tokens


# --- Subcategories de puntuació --------------------------------------------------

_SENTENCE_END_CHARS = frozenset(".!?…")
_PAUSE_CHARS = frozenset(",;:")
_QUOTE_OPEN_CHARS = frozenset("«“‘")
_QUOTE_CLOSE_CHARS = frozenset("»”")
_BRACKET_OPEN_CHARS = frozenset("([{")
_BRACKET_CLOSE_CHARS = frozenset(")]}")
_DASH_CHARS = frozenset("—–")


def punct_subkind(text: str, index: int, char: str) -> TokenSubkind:
    """Classifica un signe de puntuació aïllat segons el caràcter i el context."""
    if char in _SENTENCE_END_CHARS:
        return TokenSubkind.SENTENCE_END
    if char in _PAUSE_CHARS:
        return TokenSubkind.PAUSE
    if char in _QUOTE_OPEN_CHARS:
        return TokenSubkind.QUOTE_OPEN
    if char in _QUOTE_CLOSE_CHARS:
        return TokenSubkind.QUOTE_CLOSE
    if char in _BRACKET_OPEN_CHARS:
        return TokenSubkind.BRACKET_OPEN
    if char in _BRACKET_CLOSE_CHARS:
        return TokenSubkind.BRACKET_CLOSE
    if char in _DASH_CHARS:
        return TokenSubkind.DASH
    if char == "-":
        return TokenSubkind.HYPHEN
    if char == '"':
        opened = text.count('"', 0, index) % 2 == 0
        return TokenSubkind.QUOTE_OPEN if opened else TokenSubkind.QUOTE_CLOSE
    if char == "’":
        pending = text.count("‘", 0, index) - text.count("’", 0, index)
        return TokenSubkind.QUOTE_CLOSE if pending > 0 else TokenSubkind.APOSTROPHE
    if char == "'":
        return TokenSubkind.APOSTROPHE
    return TokenSubkind.SYMBOL


class Tokenizer:
    """Tokenitzador determinista basat en expressions regulars.

    Conserva les posicions de cada token respecte del text d'entrada, de
    manera que qualsevol token es pot localitzar exactament al text original.
    """

    def __init__(self, *, keep_spaces: bool = False) -> None:
        self._keep_spaces = keep_spaces

    def tokenize(self, text: str) -> tuple[Token, ...]:
        tokens: list[Token] = []
        for match in _TOKEN_RE.finditer(text):
            start, end = match.span()
            piece = match.group(0)
            if match.group("number") is not None:
                subkind = TokenSubkind.ORDINAL if match.group("ordinal") else None
                tokens.append(Token(piece, Span(start, end), TokenKind.NUMBER, subkind))
            elif match.group("ellipsis") is not None:
                tokens.append(
                    Token(piece, Span(start, end), TokenKind.PUNCT, TokenSubkind.SENTENCE_END)
                )
            elif match.group("chunk") is not None:
                for token in split_word_chunk(piece, start):
                    if token.kind is TokenKind.PUNCT:
                        token = token.with_subkind(
                            punct_subkind(text, token.span.start, token.text)
                        )
                    tokens.append(token)
            elif match.group("space") is not None:
                if self._keep_spaces:
                    tokens.append(Token(piece, Span(start, end), TokenKind.SPACE))
            elif match.group("punct") is not None:
                tokens.append(
                    Token(
                        piece, Span(start, end), TokenKind.PUNCT, punct_subkind(text, start, piece)
                    )
                )
            else:
                tokens.append(Token(piece, Span(start, end), TokenKind.OTHER))
        return tuple(tokens)
