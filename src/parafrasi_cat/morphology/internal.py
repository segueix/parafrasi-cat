"""Analitzador morfològic intern mínim.

Combina, per ordre de fiabilitat:

1. el lexicó de classes tancades (articles, preposicions, pronoms, auxiliars...);
2. el diccionari de formes (``resources/ca/morphology/formes.yaml``), si n'hi ha;
3. l'endevinador per sufixos, només quan les fonts anteriors no coneixen la forma.

No fa cap desambiguació: retorna totes les anàlisis compatibles amb la forma.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from parafrasi_cat.analyzer.lexicon import ClosedClassLexicon, LexiconEntry, normalize_form
from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures
from parafrasi_cat.morphology.guesser import guess
from parafrasi_cat.morphology.provider import DictionaryMorphology


class InternalMorphology:
    """Proveïdor morfològic intern basat en lexicó, diccionari i endevinador."""

    provider_id = "internal"

    def __init__(
        self,
        lexicon: ClosedClassLexicon | None = None,
        dictionary: DictionaryMorphology | None = None,
        *,
        use_guesser: bool = True,
    ) -> None:
        self._lexicon = lexicon or ClosedClassLexicon.empty()
        self._dictionary = dictionary
        self._use_guesser = use_guesser
        self._by_lemma: dict[str, list[LexiconEntry]] = defaultdict(list)
        for entry in self._lexicon.entries:
            self._by_lemma[normalize_form(entry.lemma)].append(entry)

    @property
    def lexicon(self) -> ClosedClassLexicon:
        return self._lexicon

    @property
    def dictionary(self) -> DictionaryMorphology | None:
        return self._dictionary

    def is_function_word(self, form: str) -> bool:
        """Cert si la forma pertany a una classe tancada del lexicó."""
        return self._lexicon.has(form)

    def analyze(self, form: str) -> tuple[LexicalEntry, ...]:
        entries: list[LexicalEntry] = [
            LexicalEntry(
                form,
                entry.lemma,
                MorphFeatures.from_mapping(entry.feature_dict),
                confidence=1.0,
                source=f"lexicon:{entry.word_class.value}",
            )
            for entry in self._lexicon.lookup(form)
        ]
        if self._dictionary is not None:
            entries.extend(
                replace(entry, source="dictionary") for entry in self._dictionary.analyze(form)
            )
        if not entries and self._use_guesser:
            entries.extend(guess(form))
        return _dedupe(entries)

    def generate(self, lemma: str, features: MorphFeatures) -> tuple[str, ...]:
        forms: list[str] = []
        if self._dictionary is not None:
            forms.extend(self._dictionary.generate(lemma, features))
        for entry in self._by_lemma.get(normalize_form(lemma), ()):
            if MorphFeatures.from_mapping(entry.feature_dict).matches(features):
                forms.append(entry.form)
        return tuple(dict.fromkeys(forms))


def _dedupe(entries: list[LexicalEntry]) -> tuple[LexicalEntry, ...]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    unique: list[LexicalEntry] = []
    for entry in entries:
        key = (entry.lemma.lower(), tuple(sorted(entry.features.to_dict().items())))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return tuple(unique)
