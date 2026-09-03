"""Identificació de pronoms febles.

Els pronoms febles del català apareixen de tres maneres:

- **proclítics elidits** davant d'un verb que comença en vocal: m', t', s', n', l';
- **enclítics** darrere d'un verb: -ho, -la, 'n, -me'n, -m'ho, -nos-en;
- **formes lliures** davant del verb: em, et, es, el, la, els, les, li, ho, hi,
  en, ens, us (i les formes reforçades me, te, se, ne en combinacions: se'n, me la).

Les formes «el», «la», «els», «les» coincideixen amb els articles, «en» amb la
preposició i l'article personal, i «l'» pot ser article o pronom. Sense anàlisi
sintàctica, la identificació és conservadora: aquestes formes només es marquen
com a pronom quan el context ho confirma (un altre pronom adjacent o una forma
auxiliar immediatament després); «l'» s'inclou sempre, però marcat com a ambigu.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.analyzer.tokens import Token, TokenKind, TokenSubkind
from parafrasi_cat.core.spans import Span


class PronounAttachment(StrEnum):
    PROCLITIC = "proclitic"
    """Forma elidida davant del verb: m', s', l'."""

    ENCLITIC = "enclitic"
    """Darrere del verb, amb guionet o apòstrof: -ho, 'n."""

    FREE = "free"
    """Mot independent davant del verb: em, hi, se."""


class Certainty(StrEnum):
    SURE = "sure"
    AMBIGUOUS = "ambiguous"


#: Formes que només poden ser pronoms febles.
UNAMBIGUOUS_FREE_FORMS: frozenset[str] = frozenset(
    {"em", "et", "es", "ens", "us", "li", "ho", "hi"}
)

#: Formes que també poden ser articles, preposicions o formes reforçades.
AMBIGUOUS_FREE_FORMS: frozenset[str] = frozenset(
    {"el", "la", "els", "les", "en", "me", "te", "se", "ne"}
)

_REINFORCED_FORMS: frozenset[str] = frozenset({"me", "te", "se", "ne"})

#: Forma canònica de cada variant (sense guionet i amb l'apòstrof normalitzat).
CANONICAL_FORMS: dict[str, str] = {
    "em": "em",
    "'m": "em",
    "m'": "em",
    "me": "em",
    "et": "et",
    "'t": "et",
    "t'": "et",
    "te": "et",
    "es": "es",
    "'s": "es",
    "s'": "es",
    "se": "es",
    "el": "el",
    "'l": "el",
    "l'": "el",
    "lo": "el",
    "la": "la",
    "els": "els",
    "'ls": "els",
    "los": "els",
    "les": "les",
    "li": "li",
    "ho": "ho",
    "hi": "hi",
    "en": "en",
    "'n": "en",
    "n'": "en",
    "ne": "en",
    "ens": "ens",
    "'ns": "ens",
    "nos": "ens",
    "us": "us",
    "vos": "us",
}

#: Formes auxiliars freqüents que, just després de «el/la/els/les/en/l'», confirmen
#: la lectura pronominal («el va veure», «l'he llegit», «en pot parlar»). El
#: lexicó en pot passar una llista completa.
DEFAULT_AUXILIARY_FORMS: frozenset[str] = frozenset(
    {
        "he",
        "has",
        "ha",
        "hem",
        "heu",
        "han",
        "havia",
        "havies",
        "havíem",
        "havíeu",
        "havien",
        "hauria",
        "hauries",
        "hauríem",
        "hauríeu",
        "haurien",
        "hagi",
        "hagis",
        "hàgim",
        "hàgiu",
        "hagin",
        "hagués",
        "haguessis",
        "haguéssim",
        "haguéssiu",
        "haguessin",
        "haurà",
        "hauran",
        "vaig",
        "vas",
        "va",
        "vam",
        "vau",
        "van",
        "puc",
        "pots",
        "pot",
        "podem",
        "podeu",
        "poden",
        "podia",
        "podies",
        "podíem",
        "podíeu",
        "podien",
        "podria",
        "podries",
        "podríem",
        "podríeu",
        "podrien",
        "podrà",
        "podran",
        "pugui",
        "puguin",
        "dec",
        "deus",
        "deu",
        "devem",
        "deveu",
        "deuen",
        "devia",
        "devien",
        "deuria",
        "deurien",
        "vull",
        "vols",
        "vol",
        "volem",
        "voleu",
        "volen",
        "volia",
        "volien",
        "voldria",
        "voldrien",
        "cal",
        "calen",
        "calia",
        "caldria",
        "sol",
        "solen",
        "solia",
        "solien",
    }
)


@dataclass(frozen=True, slots=True)
class WeakPronoun:
    """Un pronom feble identificat en una frase."""

    text: str
    canonical: str
    span: Span
    attachment: PronounAttachment
    certainty: Certainty
    token_index: int
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "canonical": self.canonical,
            "span": self.span.to_dict(),
            "attachment": self.attachment.value,
            "certainty": self.certainty.value,
            "token_index": self.token_index,
            "note": self.note,
        }


def canonical_form(text: str) -> str:
    """Forma canònica d'una variant de pronom feble («-me'n» no; una peça: «-me», «'n»)."""
    key = text.strip().lower().replace("’", "'").lstrip("-")
    return CANONICAL_FORMS.get(key, key)


def find_weak_pronouns(
    tokens: Sequence[Token],
    *,
    auxiliary_forms: Collection[str] = DEFAULT_AUXILIARY_FORMS,
) -> tuple[WeakPronoun, ...]:
    """Identifica els pronoms febles d'una seqüència de tokens (sense espais)."""
    words = [t for t in tokens if t.kind is not TokenKind.SPACE]
    n = len(words)
    sure: dict[int, WeakPronoun] = {}
    candidates: dict[int, str] = {}

    for index, token in enumerate(words):
        lowered = token.lower.replace("’", "'")
        if token.kind is TokenKind.CLITIC and token.subkind is TokenSubkind.PROCLITIC:
            letter = lowered[0]
            if letter == "d":
                continue  # d' és la preposició «de» elidida
            if letter == "l":
                candidates[index] = "l'"
                continue
            sure[index] = _pronoun(token, index, PronounAttachment.PROCLITIC, Certainty.SURE)
        elif token.kind is TokenKind.CLITIC and token.subkind is TokenSubkind.ENCLITIC:
            sure[index] = _pronoun(token, index, PronounAttachment.ENCLITIC, Certainty.SURE)
        elif token.kind is TokenKind.WORD:
            if lowered in UNAMBIGUOUS_FREE_FORMS:
                if lowered == "et" and index + 1 < n and words[index + 1].lower == "al":
                    continue  # «et al.» (llatí)
                sure[index] = _pronoun(token, index, PronounAttachment.FREE, Certainty.SURE)
            elif lowered in AMBIGUOUS_FREE_FORMS:
                candidates[index] = lowered

    aux = {form.lower() for form in auxiliary_forms}

    def is_pronoun(index: int) -> bool:
        return index in sure

    def next_is_clitic(index: int) -> bool:
        following = words[index + 1] if index + 1 < n else None
        return following is not None and following.kind is TokenKind.CLITIC

    def next_is_aux(index: int) -> bool:
        following = words[index + 1] if index + 1 < n else None
        return following is not None and following.lower in aux

    # Resolució dels candidats: dues passades perquè «se la» resolgui «la» per contigüitat.
    for _ in range(2):
        for index, form in list(candidates.items()):
            if index in sure:
                continue
            token = words[index]
            previous_pronoun = index > 0 and is_pronoun(index - 1)
            following_pronoun = index + 1 < n and is_pronoun(index + 1)
            following_candidate = index + 1 < n and (index + 1) in candidates
            if form in _REINFORCED_FORMS:
                if next_is_clitic(index) or following_pronoun or following_candidate:
                    sure[index] = _pronoun(token, index, PronounAttachment.FREE, Certainty.SURE)
            elif form == "l'":
                if previous_pronoun or following_pronoun or next_is_aux(index):
                    sure[index] = _pronoun(
                        token, index, PronounAttachment.PROCLITIC, Certainty.SURE
                    )
            elif form == "en":
                if previous_pronoun or next_is_aux(index):
                    sure[index] = _pronoun(token, index, PronounAttachment.FREE, Certainty.SURE)
            elif previous_pronoun or following_pronoun or next_is_aux(index):
                sure[index] = _pronoun(token, index, PronounAttachment.FREE, Certainty.SURE)

    for index, form in candidates.items():
        if form == "l'" and index not in sure:
            sure[index] = _pronoun(
                words[index],
                index,
                PronounAttachment.PROCLITIC,
                Certainty.AMBIGUOUS,
                note="pot ser l'article «el/la» elidit",
            )

    return tuple(sure[index] for index in sorted(sure))


def _pronoun(
    token: Token,
    index: int,
    attachment: PronounAttachment,
    certainty: Certainty,
    note: str = "",
) -> WeakPronoun:
    return WeakPronoun(
        text=token.text,
        canonical=canonical_form(token.text),
        span=token.span,
        attachment=attachment,
        certainty=certainty,
        token_index=index,
        note=note,
    )
