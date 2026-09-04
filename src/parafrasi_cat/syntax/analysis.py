"""Estructures i protocol de l'anàlisi sintàctica.

L'anàlisi sintàctica **només analitza**. No genera text, no completa frases,
no reescriu, no decideix estil i no inventa informació. La generació continua
sent exclusivament de les regles explícites, els diccionaris i la selecció
determinista de candidats.

És opcional: sense parser instal·lat, :class:`NullSyntax` no diu res i el
motor continua amb les heurístiques de sempre.

El parser tampoc no és infal·lible. :func:`assess_confidence` aplica un criteri
explícit de fiabilitat sobre cada arbre; quan no el supera, l'anàlisi es marca
com a poc fiable i el motor no hi autoritza cap transformació estructural.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Relacions de dependència universals que marquen un subjecte.
SUBJECT_DEPS = frozenset({"nsubj", "nsubj:pass", "csubj", "csubj:pass"})

#: Relacions que marquen un objecte o un atribut.
OBJECT_DEPS = frozenset({"obj", "iobj", "obl:arg"})

#: Relacions que obren una subordinada.
CLAUSE_DEPS = frozenset({"acl", "acl:relcl", "advcl", "ccomp", "xcomp", "csubj"})

#: Relacions de complement circumstancial.
MODIFIER_DEPS = frozenset({"obl", "obl:tmod", "obl:mod", "advmod", "nmod"})

#: Formes que neguen. Es comproven a part perquè perdre-les altera el sentit.
NEGATIONS = frozenset({"no", "mai", "cap", "ni", "gens", "tampoc"})

#: Modes que fan finit un verb. Un verb sense mode és infinitiu, gerundi o participi.
FINITE_MOODS = frozenset({"ind", "subj", "imp", "cond"})

#: Categories que poden ser nucli d'una oració (verb, o predicat nominal amb còpula).
PREDICATE_POS = frozenset({"VERB", "AUX"})

#: Etiquetes amb què el parser reconeix que no ha sabut classificar una relació.
UNRESOLVED_DEPS = frozenset({"dep", ""})

#: Relacions de còpula i d'auxiliar, per trobar el verb d'un predicat nominal.
COPULA_DEPS = frozenset({"cop", "aux", "aux:pass"})


@dataclass(frozen=True, slots=True)
class SyntaxToken:
    """Un mot analitzat, amb la seva relació de dependència.

    ``head`` és l'índex del nucli dins de la mateixa frase; a l'arrel, apunta
    a si mateix. Els intervals són relatius al text analitzat.
    """

    index: int
    text: str
    lemma: str
    pos: str
    dep: str
    head: int
    start: int
    end: int
    gender: str | None = None
    number: str | None = None
    person: str | None = None
    mood: str | None = None
    tense: str | None = None

    @property
    def is_root(self) -> bool:
        return self.dep == "ROOT" or self.head == self.index

    @property
    def is_subject(self) -> bool:
        return self.dep in SUBJECT_DEPS

    @property
    def is_object(self) -> bool:
        return self.dep in OBJECT_DEPS

    @property
    def is_negation(self) -> bool:
        return self.lemma.lower() in NEGATIONS or self.text.lower() in NEGATIONS

    @property
    def is_finite_verb(self) -> bool:
        """Cert si és un verb conjugat (té mode); un infinitiu o un participi no ho és."""
        return self.pos in PREDICATE_POS and self.mood in FINITE_MOODS

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "text": self.text,
            "lemma": self.lemma,
            "pos": self.pos,
            "dep": self.dep,
            "head": self.head,
            "gender": self.gender,
            "number": self.number,
            "person": self.person,
            "mood": self.mood,
            "tense": self.tense,
        }


@dataclass(frozen=True, slots=True)
class SyntaxConfidence:
    """Per què una anàlisi és, o no és, prou fiable per autoritzar transformacions.

    ``reasons`` és buit quan l'anàlisi supera tots els criteris; si no, diu en
    català què ha fallat, perquè el motor ho pugui explicar a qui escriu.
    """

    confident: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.confident

    def describe(self) -> str:
        if self.confident:
            return "anàlisi sintàctica fiable"
        return "anàlisi sintàctica poc fiable: " + "; ".join(self.reasons)

    def to_dict(self) -> dict[str, object]:
        return {"confident": self.confident, "reasons": list(self.reasons)}


#: Anàlisi que sempre és fiable, per als proveïdors que no en calculen cap.
TRUSTED = SyntaxConfidence(True)


def assess_confidence(
    tokens: Sequence[SyntaxToken],
    *,
    numbers_of: Callable[[str], frozenset[str]] | None = None,
) -> SyntaxConfidence:
    """Criteri explícit de confiança sintàctica.

    L'anàlisi es considera fiable quan la frase és sencera i l'arbre és
    coherent:

    1. hi ha mots analitzats;
    2. hi ha exactament una arrel (dues arrels són dos fragments);
    3. cap dependència no surt de la frase ni forma un cicle;
    4. hi ha almenys un verb conjugat;
    5. el nucli és un verb o un predicat amb còpula;
    6. el parser ha sabut classificar totes les relacions;
    7. la morfologia local no contradiu el parser en el nombre del subjecte
       ni del verb principal (només si hi ha recurs morfològic).

    Davant del dubte no s'inventa una anàlisi: es diu que no és fiable i el
    motor recorre a les heurístiques conservadores.
    """
    if not tokens:
        return SyntaxConfidence(False, ("l'analitzador no ha retornat cap mot",))
    reasons: list[str] = []
    roots = [t for t in tokens if t.is_root]
    if len(roots) != 1:
        reasons.append(f"l'oració té {len(roots)} arrels: probablement són fragments independents")
    reasons.extend(_structure_problems(tokens))
    if not any(t.is_finite_verb for t in tokens):
        reasons.append("no hi ha cap verb conjugat: sembla un fragment nominal")
    if len(roots) == 1 and not _is_predicate(roots[0], tokens):
        reasons.append(f"el nucli «{roots[0].text}» no és un verb ni un predicat amb còpula")
    unresolved = [t.text for t in tokens if t.dep in UNRESOLVED_DEPS and not t.is_root]
    if unresolved:
        reasons.append(
            "l'analitzador no ha sabut classificar " + ", ".join(f"«{t}»" for t in unresolved[:3])
        )
    if numbers_of is not None:
        reasons.extend(_morphology_contradictions(tokens, roots, numbers_of))
    return SyntaxConfidence(not reasons, tuple(reasons))


def _structure_problems(tokens: Sequence[SyntaxToken]) -> list[str]:
    """Dependències que surten de la frase o que formen un cicle."""
    problems: list[str] = []
    size = len(tokens)
    by_index = {t.index: t for t in tokens}
    for token in tokens:
        if token.head not in by_index:
            problems.append(f"la dependència de «{token.text}» apunta fora de l'oració")
            return problems
    if len(by_index) != size:  # pragma: no cover - índexs repetits: mai amb spaCy
        problems.append("hi ha índexs de mot repetits")
        return problems
    for token in tokens:
        seen = {token.index}
        current = token
        while not current.is_root:
            current = by_index[current.head]
            if current.index in seen:
                problems.append("l'arbre de dependències té un cicle")
                return problems
            seen.add(current.index)
    return problems


def _is_predicate(root: SyntaxToken, tokens: Sequence[SyntaxToken]) -> bool:
    """Cert si el nucli és un verb conjugat o un predicat nominal amb còpula."""
    if root.pos in PREDICATE_POS:
        return True
    return any(t.head == root.index and t.dep in COPULA_DEPS for t in tokens)


def _morphology_contradictions(
    tokens: Sequence[SyntaxToken],
    roots: Sequence[SyntaxToken],
    numbers_of: Callable[[str], frozenset[str]],
) -> list[str]:
    """Contradiccions de nombre entre el parser i el recurs morfològic local.

    Només es miren el subjecte i el nucli: són els mots dels quals depenen les
    condicions sintàctiques, i comparar-los tots dispararia falses alarmes amb
    formes ambigües.
    """
    problems: list[str] = []
    interesting = [t for t in tokens if t.is_subject or t in roots]
    for token in interesting:
        if token.number is None:
            continue
        known = numbers_of(token.text)
        if known and token.number not in known:
            problems.append(
                f"la morfologia diu que «{token.text}» és {'/'.join(sorted(known))} "
                f"i l'analitzador el marca com a {token.number}"
            )
    return problems


@dataclass(frozen=True, slots=True)
class SentenceSyntax:
    """Anàlisi sintàctica d'una frase.

    ``confidence`` diu si l'anàlisi és prou fiable per autoritzar
    transformacions estructurals i, si no ho és, per què.
    """

    text: str
    tokens: tuple[SyntaxToken, ...] = ()
    confidence: SyntaxConfidence = TRUSTED
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.tokens)

    @property
    def confident(self) -> bool:
        """Cert si el criteri de confiança autoritza a fer servir aquesta anàlisi."""
        return bool(self.tokens) and self.confidence.confident

    @property
    def reasons(self) -> tuple[str, ...]:
        """Motius pels quals l'anàlisi no és fiable (buit si ho és)."""
        return self.confidence.reasons

    @property
    def root(self) -> SyntaxToken | None:
        return next((t for t in self.tokens if t.is_root), None)

    @property
    def subjects(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_subject)

    @property
    def objects(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_object)

    @property
    def negations(self) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.is_negation)

    @property
    def clauses(self) -> tuple[SyntaxToken, ...]:
        """Nuclis de les subordinades (relatives, completives, adverbials)."""
        return tuple(t for t in self.tokens if t.dep in CLAUSE_DEPS)

    @property
    def coordinations(self) -> tuple[SyntaxToken, ...]:
        """Membres coordinats: perdre'n un canvia el contingut."""
        return tuple(t for t in self.tokens if t.dep == "conj")

    @property
    def n_finite_verbs(self) -> int:
        return sum(1 for t in self.tokens if t.pos in PREDICATE_POS)

    def main_subject(self) -> SyntaxToken | None:
        """Subjecte de l'oració principal, si n'hi ha un de sol i clar."""
        root = self.root
        if root is None:
            return None
        direct = [t for t in self.subjects if t.head == root.index]
        return direct[0] if len(direct) == 1 else None

    def main_verb(self) -> SyntaxToken | None:
        """Verb conjugat de l'oració principal: el nucli, o la seva còpula."""
        root = self.root
        if root is None:
            return None
        if root.is_finite_verb:
            return root
        copulas = [
            t
            for t in self.tokens
            if t.head == root.index and t.dep in COPULA_DEPS and t.is_finite_verb
        ]
        return copulas[0] if len(copulas) == 1 else None

    def subject_number(self) -> str | None:
        """Nombre del subjecte principal («sg» o «pl»), si el parser n'està segur."""
        subject = self.main_subject()
        return None if subject is None else subject.number

    def token_at(self, offset: int) -> SyntaxToken | None:
        """Mot que conté la posició de caràcter indicada."""
        return next((t for t in self.tokens if t.start <= offset < t.end), None)

    def tokens_in(self, start: int, end: int) -> tuple[SyntaxToken, ...]:
        return tuple(t for t in self.tokens if t.start >= start and t.end <= end)

    def crosses_clause_boundary(self, start: int, end: int) -> bool:
        """Cert si l'interval parteix una subordinada o una coordinació pel mig.

        Serveix per no dividir ni reordenar allà on es trencaria una relació:
        si un membre coordinat o una subordinada queda a mitges, no es toca.
        """
        inside = self.tokens_in(start, end)
        if not inside:
            return False
        indices = {t.index for t in inside}
        for token in self.tokens:
            if token.dep not in CLAUSE_DEPS and token.dep != "conj":
                continue
            # El nucli d'una relació dins de l'interval ha de tenir el seu cap
            # també a dins; si no, la relació queda partida.
            if token.index in indices and token.head not in indices:
                return True
            if token.index not in indices and token.head in indices:
                return True
        return False

    def describe(self) -> str:
        root = self.root
        subject = self.main_subject()
        parts = [f"arrel: {root.text if root else '?'}"]
        if subject is not None:
            parts.append(f"subjecte: {subject.text} ({subject.number or 'nombre desconegut'})")
        if self.objects:
            parts.append("objecte: " + ", ".join(t.text for t in self.objects))
        if self.clauses:
            parts.append(f"subordinades: {len(self.clauses)}")
        if self.coordinations:
            parts.append(f"coordinacions: {len(self.coordinations)}")
        if self.negations:
            parts.append("negació: " + ", ".join(t.text for t in self.negations))
        if not self.confident:
            parts.append(self.confidence.describe())
        return " · ".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "confident": self.confident,
            "confidence": self.confidence.to_dict(),
            "source": self.source,
            "tokens": [t.to_dict() for t in self.tokens],
        }


@runtime_checkable
class SyntaxProvider(Protocol):
    """Analitzador sintàctic local. Només analitza; mai no genera res."""

    @property
    def available(self) -> bool:
        """Cert si l'analitzador està instal·lat i carregat."""
        ...

    def parse(self, text: str) -> SentenceSyntax:
        """Anàlisi d'una frase. Buida si l'analitzador no hi és o no en sap prou."""
        ...


class NullSyntax:
    """Analitzador que no sap res. És el que hi ha si no s'ha instal·lat cap parser."""

    available = False

    def parse(self, text: str) -> SentenceSyntax:
        return empty(text)


class CachedSyntax:
    """Recorda les anàlisis d'una sessió per no analitzar dos cops el mateix text.

    La memòria cau és només en memòria, mai a disc, i no afecta el
    determinisme: la mateixa frase ja donava la mateixa anàlisi. Quan s'omple,
    es buida sencera en lloc de créixer sense límit.
    """

    def __init__(self, provider: SyntaxProvider, *, max_entries: int = 2048) -> None:
        self._provider = provider
        self._max_entries = max_entries
        self._cache: dict[str, SentenceSyntax] = {}
        self._parses = 0
        self._hits = 0

    @property
    def provider(self) -> SyntaxProvider:
        return self._provider

    @property
    def available(self) -> bool:
        return self._provider.available

    @property
    def statistics(self) -> dict[str, int]:
        return {"parses": self._parses, "cache_hits": self._hits, "cached": len(self._cache)}

    def parse(self, text: str) -> SentenceSyntax:
        cached = self._cache.get(text)
        if cached is not None:
            self._hits += 1
            return cached
        analysis = self._provider.parse(text)
        self._parses += 1
        if len(self._cache) >= self._max_entries:
            self._cache.clear()
        self._cache[text] = analysis
        return analysis


def agree(
    first: SyntaxToken | None, second: SyntaxToken | None, feature: str = "number"
) -> bool | None:
    """Cert si els dos mots comparteixen el tret; ``None`` si no se sap."""
    if first is None or second is None:
        return None
    left: object = getattr(first, feature)
    right: object = getattr(second, feature)
    if left is None or right is None:
        return None
    return bool(left == right)


def merge(*analyses: SentenceSyntax) -> SentenceSyntax:  # pragma: no cover - utilitat
    """Primera anàlisi amb contingut, per encadenar proveïdors."""
    for analysis in analyses:
        if analysis:
            return analysis
    return empty(analyses[0].text if analyses else "")


def token_features(token: SyntaxToken) -> dict[str, str]:
    """Trets del mot en el vocabulari que fan servir les condicions de les regles."""
    features: dict[str, str] = {"lemma": token.lemma, "pos": token.pos, "dep": token.dep}
    for name in ("gender", "number", "person", "mood", "tense"):
        value = getattr(token, name)
        if value is not None:
            features[name] = value
    return features


DEFAULT_FIELDS: tuple[str, ...] = ("lemma", "pos", "dep", "gender", "number", "person")

_NO_TOKENS = SyntaxConfidence(False, ("l'analitzador no ha retornat cap mot",))
_EMPTY: SentenceSyntax = SentenceSyntax("", (), _NO_TOKENS, "null")


def empty(text: str = "") -> SentenceSyntax:
    return SentenceSyntax(text, (), _NO_TOKENS, "null") if text else _EMPTY


__all__ = [
    "CLAUSE_DEPS",
    "COPULA_DEPS",
    "DEFAULT_FIELDS",
    "FINITE_MOODS",
    "MODIFIER_DEPS",
    "NEGATIONS",
    "OBJECT_DEPS",
    "SUBJECT_DEPS",
    "TRUSTED",
    "CachedSyntax",
    "NullSyntax",
    "SentenceSyntax",
    "SyntaxConfidence",
    "SyntaxProvider",
    "SyntaxToken",
    "agree",
    "assess_confidence",
    "empty",
    "merge",
    "token_features",
]
