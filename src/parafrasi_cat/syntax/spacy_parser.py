"""Analitzador sintàctic català local basat en spaCy.

Model: ``ca_core_news_sm`` (spaCy), entrenat sobre UD Catalan AnCora. Aporta
dependències, categories gramaticals, trets morfològics i lemes. Cap component
no és generatiu: el model **només analitza**.

És opcional i mandrós: el model es carrega la primera vegada que es demana i
es reutilitza durant tota la sessió. Sense spaCy o sense el model instal·lat,
:attr:`SpacySyntax.available` és fals i el motor continua amb les seves
heurístiques.

Llicència: spaCy MIT; model ``ca_core_news_sm`` GPL-3.0. Vegeu
``THIRD_PARTY_LICENSES.md``.
"""

from __future__ import annotations

from typing import Any

from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken, empty

DEFAULT_MODEL = "ca_core_news_sm"
SOURCE = "spacy"

#: Components del model que no calen per analitzar l'estructura. Desactivar-los
#: estalvia temps i memòria sense perdre res del que fan servir les regles.
DISABLED_COMPONENTS = ("ner",)

_GENDER = {"Masc": "m", "Fem": "f"}
_NUMBER = {"Sing": "sg", "Plur": "pl"}


class SpacySyntax:
    """Adaptador de spaCy. Carrega el model una sola vegada i el reutilitza."""

    def __init__(self, model: str = DEFAULT_MODEL, *, eager: bool = False) -> None:
        self._model_name = model
        self._nlp: Any = None
        self._loaded = False
        self._failure = ""
        if eager:
            self._load()

    # -- càrrega ---------------------------------------------------------------------------

    def _load(self) -> Any:
        if self._loaded:
            return self._nlp
        self._loaded = True
        try:
            import spacy  # noqa: PLC0415 - import mandrós: spaCy és opcional
        except ImportError as exc:
            self._failure = f"spaCy no està instal·lat ({exc})"
            return None
        try:
            self._nlp = spacy.load(self._model_name, disable=list(DISABLED_COMPONENTS))
        except (OSError, ValueError) as exc:
            self._failure = f"El model «{self._model_name}» no està instal·lat ({exc})"
            self._nlp = None
        return self._nlp

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
        document = nlp(text)
        tokens = tuple(_convert(token) for token in document if not token.is_space)
        return SentenceSyntax(text, tokens, confident=bool(tokens), source=SOURCE)

    def parse_many(self, texts: list[str]) -> list[SentenceSyntax]:
        """Analitza diversos textos aprofitant el processament per lots de spaCy."""
        nlp = self._load()
        if nlp is None:
            return [empty(text) for text in texts]
        results: list[SentenceSyntax] = []
        for text, document in zip(texts, nlp.pipe(texts), strict=True):
            tokens = tuple(_convert(token) for token in document if not token.is_space)
            results.append(SentenceSyntax(text, tokens, confident=bool(tokens), source=SOURCE))
        return results


def _convert(token: Any) -> SyntaxToken:
    """Converteix un token de spaCy a l'estructura del motor."""
    morph = token.morph
    return SyntaxToken(
        index=token.i,
        text=token.text,
        lemma=token.lemma_ or token.text,
        pos=token.pos_,
        dep=token.dep_,
        head=token.head.i,
        start=token.idx,
        end=token.idx + len(token.text),
        gender=_first(morph.get("Gender"), _GENDER),
        number=_first(morph.get("Number"), _NUMBER),
        person=_first(morph.get("Person"), None),
    )


def _first(values: Any, table: dict[str, str] | None) -> str | None:
    if not values:
        return None
    value = str(values[0])
    return table.get(value) if table is not None else value


def discover(model: str = DEFAULT_MODEL) -> SpacySyntax | None:
    """Analitzador si el model està instal·lat; ``None`` altrament."""
    parser = SpacySyntax(model)
    return parser if parser.available else None
