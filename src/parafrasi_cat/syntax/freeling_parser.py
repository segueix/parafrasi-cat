"""FreeLing local: CoNLL explícit, alineament estricte i etiquetes conservadores.

No s'assumeix que CoNLL de FreeLing sigui UD. Només es normalitzen relacions
inequívoques; les desconegudes bloquegen la confiança. No hi ha xarxa.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from parafrasi_cat.morphology.adapters.freeling import decode_eagles
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken, assess_confidence, empty

# Correspondències bàsiques d'etiquetes FreeLing; cap conversió d'arbres
# preposicionals o de subordinades sense una correspondència demostrada.
DEPS = {"subj": "nsubj", "suj": "nsubj", "dobj": "obj", "cd": "obj",
        "aux": "aux", "iobj": "iobj", "ci": "iobj", "spec": "det", "det": "det",
        "adj": "amod", "amod": "amod", "punct": "punct", "f": "punct"}
POS = {"noun": "NOUN", "propn": "PROPN", "verb": "VERB", "aux": "AUX",
       "adj": "ADJ", "det": "DET", "pron": "PRON", "adv": "ADV",
       "adp": "ADP", "num": "NUM", "punct": "PUNCT", "conj": "CCONJ"}


def parse_columns(text: str, output: str) -> SentenceSyntax:
    """ID FORM LEMMA TAG DEPHEAD DEPREL. Una sola frase, cobertura exacta."""
    rows = [line.split() for line in output.splitlines() if line.strip()]
    tokens = []
    cursor = 0
    try:
        for i, row in enumerate(rows):
            if len(row) != 6:
                return empty(text)
            ident, form, lemma, tag, parent, relation = row
            if int(ident) != i + 1:
                return empty(text)
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if not text.startswith(form, cursor):
                return empty(text)  # multiwords, contraccions retokenitzades, etc.
            head = int(parent) - 1
            if not -1 <= head < len(rows):
                return empty(text)
            f = decode_eagles(tag)
            dep = "ROOT" if head == -1 else DEPS.get(relation.lower(), "dep")
            tokens.append(SyntaxToken(
                index=i, text=form, lemma=lemma, pos=POS.get(f.pos, "X"),
                dep=dep, head=i if head == -1 else head, start=cursor, end=cursor + len(form),
                gender=f.gender, number=f.number, person=f.person, mood=f.mood, tense=f.tense,
                verb_form={"inf": "Inf", "part": "Part", "ger": "Ger"}.get(f.mood,
                    "Fin" if f.pos in ("verb", "aux") and f.mood else None),
            ))
            cursor += len(form)
        if text[cursor:].strip():
            return empty(text)
        result = tuple(tokens)
        return SentenceSyntax(text, result, assess_confidence(result), "freeling")
    except (ValueError, IndexError):
        return empty(text)


class FreeLingSyntax:
    """Procés local amb límit de temps; l'absència o error dona anàlisi buida."""
    def __init__(self, command: str | None = None, config: str | None = None,
                 timeout: float = 30.0) -> None:
        self.command = command or os.environ.get("PARAFRASI_FREELING_COMMAND", "analyze")
        self.config = config or os.environ.get("PARAFRASI_FREELING_CONFIG", "ca.cfg")
        self.timeout = timeout
        self.failure = ""
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = bool(shutil.which(self.command)) and self.parse("El rei governa.").confident
        return self._available

    def parse(self, text: str) -> SentenceSyntax:
        if not text.strip() or not shutil.which(self.command):
            return empty(text)
        try:
            result = subprocess.run([
                self.command, "-f", self.config, "--input", "text", "--output", "conll",
                "--outlv", "dep", "--oconll", str(Path(__file__).with_name("freeling-columns.cfg")),
                "--noflush",
            ], input=text + "\n", capture_output=True, text=True, timeout=self.timeout, check=False)
            if result.returncode:
                self.failure = "FreeLing no ha pogut analitzar amb la configuració catalana local."
                return empty(text)
            return parse_columns(text, result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            self.failure = "FreeLing no disponible o temps d'anàlisi excedit."
            return empty(text)


class PreferredSyntax:
    """FreeLing primer; parser existent quan l'arbre no és prou fiable."""
    def __init__(self, primary, fallback) -> None:
        self.primary, self.fallback = primary, fallback

    @property
    def available(self) -> bool:
        return self.primary.available or self.fallback.available

    def parse(self, text: str) -> SentenceSyntax:
        first = self.primary.parse(text)
        if first.confident or not self.fallback.available:
            return first
        second = self.fallback.parse(text)
        return second if second.confident else first
