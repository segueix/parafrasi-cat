"""Analitzador sintàctic català local basat en spaCy.

Models: ``ca_core_news_sm`` / ``md`` / ``lg`` (spaCy), tots entrenats sobre UD
Catalan AnCora. Aporten dependències, categories gramaticals, trets
morfològics i lemes. Cap component no és generatiu: el model **només
analitza**.

Els tres models tenen el mateix esquema d'etiquetes i la mateixa llicència; es
diferencien només en la mida i en l'exactitud de l'anàlisi. Per això, quan no
se n'indica cap, es fa servir **el més exacte dels que hi ha instal·lats**
(:data:`PREFERRED_MODELS`): triar un analitzador millor entrenat no és cap
heurística sobre les frases, i el criteri de confiança
(:func:`~parafrasi_cat.syntax.analysis.assess_confidence`) continua rebutjant
igualment les anàlisis que no siguin coherents. Es pot fixar un model concret
amb el paràmetre ``model``, amb ``syntax: spacy:<model>`` a la configuració o
amb la variable d'entorn ``PARAFRASI_SPACY_MODEL``.

És opcional i mandrós: el model es carrega la primera vegada que es demana i
es reutilitza durant tota la sessió. Sense spaCy o sense cap model instal·lat,
:attr:`SpacySyntax.available` és fals i el motor continua amb les seves
heurístiques.

Llicència: spaCy MIT; models ``ca_core_news_*`` GPL-3.0. Vegeu
``THIRD_PARTY_LICENSES.md``.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from collections.abc import Callable
from typing import Any

from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.syntax.analysis import (
    SentenceSyntax,
    SyntaxToken,
    assess_confidence,
    empty,
)

DEFAULT_MODEL = "ca_core_news_sm"
"""Model mínim: el que instal·la ``scripts/install_parser.py`` per defecte."""

#: Models catalans coneguts, del més exacte al més lleuger. Tots analitzen la
#: mateixa llengua amb el mateix esquema d'etiquetes; el gran s'equivoca menys.
PREFERRED_MODELS: tuple[str, ...] = ("ca_core_news_lg", "ca_core_news_md", DEFAULT_MODEL)

#: Variable d'entorn que fixa el model, per damunt de la tria automàtica.
MODEL_ENV = "PARAFRASI_SPACY_MODEL"

SOURCE = "spacy"


def installed_models(candidates: tuple[str, ...] = PREFERRED_MODELS) -> tuple[str, ...]:
    """Models de la llista que estan instal·lats, en el mateix ordre.

    Només es mira si el paquet del model existeix; no se'n carrega cap, de
    manera que la comprovació és barata i no té cap efecte.
    """
    found: list[str] = []
    for name in candidates:
        try:
            if importlib.util.find_spec(name) is not None:
                found.append(name)
        except (ImportError, ValueError):  # pragma: no cover - paquet malmès
            continue
    return tuple(found)


def best_installed_model(candidates: tuple[str, ...] = PREFERRED_MODELS) -> str:
    """El model més exacte que hi ha instal·lat; el mínim si no n'hi ha cap.

    Amb ``PARAFRASI_SPACY_MODEL`` definida mana la variable d'entorn, encara
    que el model no hi sigui: així l'error és explícit i no queda amagat.
    """
    forced = os.environ.get(MODEL_ENV, "").strip()
    if forced:
        return forced
    found = installed_models(candidates)
    return found[0] if found else (candidates[-1] if candidates else DEFAULT_MODEL)

#: Components del model que no calen per analitzar l'estructura. Desactivar-los
#: estalvia temps i memòria sense perdre res del que fan servir les regles.
DISABLED_COMPONENTS = ("ner",)

_GENDER = {"Masc": "m", "Fem": "f"}
_NUMBER = {"Sing": "sg", "Plur": "pl"}
_MOOD = {"Ind": "ind", "Sub": "subj", "Imp": "imp", "Cnd": "cond"}
_TENSE = {"Pres": "pres", "Past": "past", "Imp": "impf", "Fut": "fut"}


class SpacySyntax:
    """Adaptador de spaCy. Carrega el model una sola vegada i el reutilitza."""

    def __init__(
        self,
        model: str = "",
        *,
        eager: bool = False,
        morphology: MorphologyProvider | None = None,
    ) -> None:
        self._model_name = model or best_installed_model()
        self._morphology = morphology
        self._nlp: Any = None
        self._loaded = False
        self._failure = ""
        # Amb el mode de xarxa local hi pot haver dues peticions alhora: sense
        # pany, la segona veuria el model «carregat» mentre encara s'està
        # carregant i es pensaria que el parser no hi és.
        self._load_lock = threading.Lock()
        if eager:
            self._load()

    # -- càrrega ---------------------------------------------------------------------------

    def _load(self) -> Any:
        if self._loaded:
            return self._nlp
        with self._load_lock:
            if not self._loaded:
                self._nlp = self._load_model()
                self._loaded = True
            return self._nlp

    def _load_model(self) -> Any:
        try:
            import spacy  # noqa: PLC0415 - import mandrós: spaCy és opcional
        except ImportError as exc:
            self._failure = f"spaCy no està instal·lat ({exc})"
            return None
        try:
            return spacy.load(self._model_name, disable=list(DISABLED_COMPONENTS))
        except (OSError, ValueError) as exc:
            self._failure = f"El model «{self._model_name}» no està instal·lat ({exc})"
            return None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def available(self) -> bool:
        """Cert si spaCy i el model català es poden carregar."""
        return self._load() is not None

    @property
    def failure(self) -> str:
        """Motiu pel qual no està disponible (buit si ho està)."""
        self._load()
        return self._failure

    def version(self) -> str:
        nlp = self._load()
        if nlp is None:
            return ""
        meta = getattr(nlp, "meta", {})
        return f"{meta.get('lang', '')}_{meta.get('name', '')}-{meta.get('version', '')}"

    def license(self) -> str:
        nlp = self._load()
        if nlp is None:
            return ""
        return str(getattr(nlp, "meta", {}).get("license", ""))

    def describe(self) -> str:
        if not self.available:
            return self._failure or "Analitzador sintàctic no disponible"
        return f"spaCy {self.version()} ({self._model_name})"

    # -- anàlisi ---------------------------------------------------------------------------

    def parse(self, text: str) -> SentenceSyntax:
        """Analitza una frase. Retorna una anàlisi buida si el model no hi és."""
        nlp = self._load()
        if nlp is None or not text.strip():
            return empty(text)
        document = nlp(prepare_text(text))
        return self._analysis(text, document)

    def parse_many(self, texts: list[str]) -> list[SentenceSyntax]:
        """Analitza diversos textos aprofitant el processament per lots de spaCy."""
        nlp = self._load()
        if nlp is None:
            return [empty(text) for text in texts]
        prepared = [prepare_text(text) for text in texts]
        return [
            self._analysis(text, document)
            for text, document in zip(texts, nlp.pipe(prepared), strict=True)
        ]

    def _analysis(self, text: str, document: Any) -> SentenceSyntax:
        """Converteix un document de spaCy i n'avalua la fiabilitat.

        Els mots conserven els caràcters del text original (l'apòstrof
        tipogràfic inclòs): la normalització només serveix perquè el model
        segmenti bé, i no canvia cap posició.
        """
        tokens = tuple(_convert(token, text) for token in document if not token.is_space)
        confidence = assess_confidence(tokens, numbers_of=self._numbers_of)
        return SentenceSyntax(text, tokens, confidence, SOURCE)

    @property
    def _numbers_of(self) -> Callable[[str], frozenset[str]] | None:
        """Nombres que el recurs morfològic local admet per a una forma."""
        morphology = self._morphology
        if morphology is None:
            return None

        def numbers(form: str) -> frozenset[str]:
            return frozenset(
                entry.features.number
                for entry in morphology.analyze(form)
                if entry.features.number is not None
            )

        return numbers


#: Apòstrofs i cometes simples tipogràfics que el model no segmenta com l'apòstrof
#: recte («d’aquests» sortia com un verb). Cada caràcter es canvia per un altre
#: d'un sol caràcter: les posicions no es mouen.
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})


def prepare_text(text: str) -> str:
    """Text tal com es passa al model: apòstrofs tipogràfics convertits en rectes."""
    return text.translate(_APOSTROPHES)


def _convert(token: Any, original: str = "") -> SyntaxToken:
    """Converteix un token de spaCy a l'estructura del motor."""
    morph = token.morph
    start = token.idx
    end = token.idx + len(token.text)
    surface = original[start:end] if original and len(original) >= end else token.text
    return SyntaxToken(
        index=token.i,
        text=surface,
        lemma=token.lemma_ or token.text,
        pos=token.pos_,
        dep=token.dep_,
        head=token.head.i,
        start=token.idx,
        end=token.idx + len(token.text),
        gender=_first(morph.get("Gender"), _GENDER),
        number=_first(morph.get("Number"), _NUMBER),
        person=_first(morph.get("Person"), None),
        mood=_first(morph.get("Mood"), _MOOD),
        tense=_first(morph.get("Tense"), _TENSE),
        verb_form=_first(morph.get("VerbForm"), None),
        pron_type=_first(morph.get("PronType"), None),
        adv_type=_first(morph.get("AdvType"), None),
        reflexive=_reflexive(morph),
    )


def _reflexive(morph: Any) -> bool | None:
    """``Reflex=Yes`` del model; ``None`` si el model no en diu res."""
    values = morph.get("Reflex")
    return str(values[0]) == "Yes" if values else None


def _first(values: Any, table: dict[str, str] | None) -> str | None:
    if not values:
        return None
    value = str(values[0])
    return table.get(value) if table is not None else value


def discover(model: str = "") -> SpacySyntax | None:
    """Analitzador si hi ha model instal·lat; ``None`` altrament.

    Sense nom de model es fa servir el més exacte dels instal·lats
    (:func:`best_installed_model`).
    """
    parser = SpacySyntax(model)
    return parser if parser.available else None
