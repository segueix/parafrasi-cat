"""Utilitats de text independents de la llengua concreta."""

from __future__ import annotations

import re

#: Classe de caràcters que representa una lletra (qualsevol alfabet), sense
#: dígits ni guió baix. Es fa servir per construir límits de paraula fiables
#: amb text en català (accents, ç, l·l, etc.).
LETTER = r"[^\W\d_]"

#: Apòstrofs que es consideren equivalents (recte i tipogràfic).
APOSTROPHES = "'’"

_APOSTROPHE_RE = re.compile("[" + APOSTROPHES + "]")


def phrase_pattern(phrase: str, *, ignore_case: bool = True) -> re.Pattern[str]:
    """Construeix un patró que troba ``phrase`` com a paraula o locució sencera.

    - Els espais de la locució accepten qualsevol seqüència d'espais en blanc.
    - Els apòstrofs accepten tant l'apòstrof recte com el tipogràfic.
    - El patró exigeix que no hi hagi lletres immediatament abans ni després,
      de manera que «cap» no coincideixi dins de «capital».
    """
    parts = [re.escape(part) for part in phrase.split()]
    if not parts:
        raise ValueError("La locució no pot ser buida")
    body = r"\s+".join(parts)
    body = _APOSTROPHE_RE.sub("[" + APOSTROPHES + "]", body)
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(rf"(?<!{LETTER}){body}(?!{LETTER})", flags)


def match_casing(reference: str, text: str) -> str:
    """Adapta les majúscules de ``text`` al patró de ``reference``.

    - Si la referència és tota en majúscules (i té més d'una lletra), el
      resultat també ho serà.
    - Si la referència comença amb majúscula, el resultat també.
    - Altrament, ``text`` es retorna sense canvis.
    """
    if not reference or not text:
        return text
    letters = [c for c in reference if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return text.upper()
    if reference[0].isupper():
        return text[0].upper() + text[1:]
    return text


def normalize_apostrophes(text: str) -> str:
    """Substitueix l'apòstrof tipogràfic pel recte (útil per comparar)."""
    return text.replace("’", "'")
