"""Substitució atòmica de grups nominals simples amb morfologia coneguda.

No resol coordinacions, relatives ni concordança amb predicats externs.
Si no es pot justificar cada forma, no autoritza la substitució.
"""
from __future__ import annotations

import re
from dataclasses import replace

from parafrasi_cat.core.text import match_casing
from parafrasi_cat.morphology.features import MorphFeatures
from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken

_ARTICLES = {"el", "la", "els", "les", "l'", "l’"}
_CONTRACTED = {"del": ("de", "el"), "dels": ("de", "els"),
               "al": ("a", "el"), "als": ("a", "els"),
               "pel": ("per", "el"), "pels": ("per", "els")}


def nominal_span(parsed: SentenceSyntax, noun: SyntaxToken) -> tuple[int, int] | None:
    members = parsed.subtree(noun)
    # Only a contiguous, simple nominal group: no shared or distant agreement.
    if noun.dep in {"conj", "appos"} or noun.is_root:
        return None
    for t in members:
        if t.index == noun.index:
            continue
        if not ((t.head == noun.index and t.dep.split(':')[0] in {"det", "amod", "case"}
                 and t.pos in {"DET", "ADJ", "ADP"})
                or (t.dep == "advmod" and t.pos == "ADV"
                    and any(a.index == t.head and a.dep == "amod" for a in members))):
            return None
    start, end = min(t.start for t in members), max(t.end for t in members)
    ordered = sorted(members, key=lambda t: t.start)
    if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
        return None
    if any(t not in members for t in parsed.tokens_in(start, end)):
        return None
    # A copular adjective/participle outside the group could also agree.
    parent = next((t for t in parsed.tokens if t.index == noun.head), None)
    if parent and (parent.pos == "ADJ" or parent.verb_form == "Part"):
        return None
    if any(t.dep in {"xcomp", "acl", "acl:relcl"} for t in parsed.tokens):
        return None
    return start, end


def replacement(parsed: SentenceSyntax, noun: SyntaxToken, lemma: str,
                morphology: MorphologyProvider) -> str | None:
    span = nominal_span(parsed, noun)
    if span is None or noun.number not in {"sg", "pl"} or ' ' in lemma:
        return None
    entries = [e for e in morphology.analyze(lemma)
               if e.features.pos == "noun" and e.features.gender in {"m", "f"}
               and e.confidence >= .9]
    genders = {e.features.gender for e in entries}
    if len(genders) != 1:
        return None
    gender = next(iter(genders))
    forms = morphology.generate(entries[0].lemma, MorphFeatures(
        pos="noun", gender=gender, number=noun.number))
    if not forms:
        return None
    members = list(parsed.tokens_in(*span))
    output: list[str] = []
    for t in members:
        low = t.text.lower()
        if t.index == noun.index:
            value = forms[0]
        elif low in _ARTICLES or low in _CONTRACTED:
            article = ("el" if gender == "m" else "la") if noun.number == "sg" else (
                "els" if gender == "m" else "les")
            value = (_CONTRACTED[low][0] + " " if low in _CONTRACTED else "") + article
        elif t.pos in {"DET", "ADJ"}:
            choices = []
            for entry in morphology.analyze(t.text):
                if entry.features.pos != t.pos.lower() or entry.confidence < .9:
                    continue
                choices.extend(morphology.generate(entry.lemma, replace(
                    entry.features, gender=gender, number=noun.number)))
            if not choices:
                return None
            value = choices[0]
        elif t.pos == "ADP" and low in {"d'", "d’"}:
            value = "de"
        else:
            value = t.text
        output.append(match_casing(t.text, value))
    # Apostrophise against the immediately following word (possibly an adjective).
    for i in range(len(output) - 1):
        words = output[i].lower().split()
        if not words or words[-1] not in {"el", "la"}:
            continue
        following = output[i + 1].lower()
        sound = following[1:] if following.startswith('h') else following
        # Unstressed i/u and semivowels need lexical phonology: abstain.
        if sound.startswith(('i', 'u', 'ï', 'ü', 'y')):
            return None
        if sound.startswith(tuple('aeoàèéíòóú')):
            output[i] = match_casing(output[i], ' '.join(words[:-1] + ["l’"]))
    for i in range(len(output) - 1):
        if output[i].lower() != "de":
            continue
        following = output[i + 1].lower().removeprefix("h")
        if following in {"el", "els"}:
            continue
        if following in {"un", "una", "uns", "unes"}:
            output[i] = match_casing(output[i], "d’")
            continue
        if following.startswith(("i", "u", "ï", "ü", "y")):
            return None
        if following.startswith(tuple("aeoàèéíòóú")):
            output[i] = match_casing(output[i], "d’")
    result = ''
    for i, value in enumerate(output):
        if i:
            gap = parsed.text[members[i-1].end:members[i].start]
            result += '' if result.endswith(("'", '’')) else (gap or ' ')
        result += value
    for prep, contracted in (("de", "de"), ("a", "a"), ("per", "pe")):
        for article in ("el", "els"):
            result = re.sub(r'\b' + prep + ' ' + article + r'\b',
                            lambda m: match_casing(m.group(), contracted + article[1:]),
                            result, flags=re.IGNORECASE)
    return result
