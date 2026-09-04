"""Evidència morfosintàctica que una forma és un verb finit de passat simple.

Una regla que canvia «encarregà» per «va encarregar» ha de saber que
«encarregà» és, en aquesta frase, un verb conjugat en passat. Que la forma
*acabi* com un passat simple no ho garanteix: «sobirà», «germà», «català» o
«sofà» acaben igual i són adjectius o noms, i en una construcció el·líptica
(«era rei, però ja no sobirà») no hi ha cap verb que la negació pugui
acompanyar.

Aquí es combinen totes les fonts locals disponibles, cadascuna amb el pes que
li toca, i es decideix de manera explícita i explicable:

1. **Lectures lèxiques** del recurs morfològic (Softcatalà, lexicó de classes
   tancades, diccionari de formes). Només compten les lectures de
   coneixement lèxic; les hipòtesis de l'endevinador per sufixos s'ignoren,
   perquè el que es vol descartar és precisament una hipòtesi per sufix.
2. **Taula d'irregulars** i **terminacions** del passat simple, que aporten
   la lectura verbal quan el recurs no coneix la forma.
3. **Analitzador sintàctic**, quan es refia de l'anàlisi: categoria,
   forma verbal, temps, relació de dependència i nucli. Resol les formes
   ambigües i descarta les que fan de nom o d'adjectiu; també descarta
   qualsevol forma que llegeixi com a futur.
4. **Context immediat**: un pronom feble segur just davant («hi arribà»,
   «ho digué») només pot acompanyar un verb. La negació sola no és cap
   evidència: «no» precedeix igualment un adjectiu («però no independent»).

Regla de decisió (resumida):

- el recurs coneix la forma i només hi veu un verb de passat → verb;
- el recurs hi veu un verb de passat i també un nom o un adjectiu → verb
  només si l'analitzador la veu com a verb en funció verbal o un pronom
  feble segur la precedeix; si no, **ambigua**: no es transforma;
- el recurs coneix la forma i no hi veu cap verb de passat → **no és un
  verb**: no es transforma, digui el que digui l'analitzador;
- el recurs no la coneix: la taula d'irregulars i les terminacions de plural
  són prou específiques (llevat que l'analitzador la vegi com a nom o adjectiu);
  una terminació de singular («-à», «-í») només val amb l'analitzador a favor
  o amb un pronom feble segur al davant.

En tots els casos, dubte vol dir conservar l'original, i el motiu queda
escrit perquè el resultat el pugui ensenyar.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parafrasi_cat.morphology.features import LexicalEntry
from parafrasi_cat.morphology.guesser import guess
from parafrasi_cat.morphology.provider import MorphologyProvider
from parafrasi_cat.syntax.analysis import FINITE_MOODS, PREDICATE_POS, SentenceSyntax, SyntaxToken

#: Fonts de lectura que són coneixement lèxic i no una hipòtesi per sufix.
GUESSER_SOURCE = "guesser"
#: Confiança mínima perquè una lectura compti com a coneixement lèxic.
LEXICAL_MIN_CONFIDENCE = 0.9

#: Categories que l'analitzador dona a un mot que fa de nom, adjectiu o similar.
NOMINAL_POS = frozenset({"NOUN", "ADJ", "PROPN", "PRON", "ADV", "DET", "NUM"})
#: Relacions de dependència pròpies d'un constituent nominal o de modificador.
NOMINAL_DEPS = frozenset(
    {
        "amod",
        "nmod",
        "nmod:poss",
        "nsubj",
        "nsubj:pass",
        "obj",
        "iobj",
        "obl",
        "obl:arg",
        "obl:tmod",
        "obl:mod",
        "appos",
        "det",
        "nummod",
        "flat",
        "compound",
        "fixed",
    }
)
#: Relacions amb què un verb conjugat encapçala una clàusula.
CLAUSAL_DEPS = frozenset(
    {
        "ROOT",
        "root",
        "conj",
        "ccomp",
        "xcomp",
        "advcl",
        "acl",
        "acl:relcl",
        "parataxis",
        "csubj",
        "csubj:pass",
    }
)

#: Auxiliar del passat perifràstic segons persona i nombre.
AUXILIARIES: dict[tuple[str, str], str] = {
    ("3", "sg"): "va",
    ("3", "pl"): "van",
    ("1", "pl"): "vam",
    ("2", "pl"): "vau",
}


class Verdict(StrEnum):
    """Conclusió sobre una forma."""

    VERB = "verb"
    """Evidència suficient: és un verb finit de passat simple en funció verbal."""

    AMBIGUOUS = "ambiguous"
    """Podria ser un verb, però cap font no resol el dubte: no es transforma."""

    NOT_VERB = "not_verb"
    """No és un verb de passat (nom, adjectiu, futur...): no es transforma."""

    UNKNOWN = "unknown"
    """Cap font no en sap prou: no es transforma."""


@dataclass(frozen=True, slots=True)
class LexicalReadings:
    """Lectures lèxiques (no endevinades) d'una forma."""

    known: bool
    past_verb: tuple[LexicalEntry, ...] = ()
    other_verb: tuple[LexicalEntry, ...] = ()
    non_verb: tuple[LexicalEntry, ...] = ()

    @property
    def only_past_verb(self) -> bool:
        return bool(self.past_verb) and not self.non_verb

    @property
    def ambiguous(self) -> bool:
        return bool(self.past_verb) and bool(self.non_verb)

    def describe_non_verb(self) -> str:
        labels = {
            "noun": "un nom",
            "adj": "un adjectiu",
            "adv": "un adverbi",
            "propn": "un nom propi",
            "pron": "un pronom",
            "det": "un determinant",
        }
        seen = dict.fromkeys(
            labels.get(e.features.pos or "", "una altra categoria") for e in self.non_verb
        )
        return " o ".join(seen) if seen else "una altra categoria"


@dataclass(frozen=True, slots=True)
class ParserView:
    """Què diu l'analitzador d'un mot concret d'una frase fiable."""

    token: SyntaxToken
    head: SyntaxToken
    verbal: bool
    """Verb conjugat que encapçala una clàusula (o coordinat amb un altre verb)."""
    nominal: bool
    """Fa de nom, d'adjectiu o de modificador (o va coordinat amb un nom)."""
    future: bool
    """L'analitzador hi llegeix un futur: mai no és un passat simple."""

    def describe(self) -> str:
        if self.nominal and self.token.dep == "conj":
            return f"l'analitzador la veu coordinada amb «{self.head.text}», que no és cap verb"
        if self.nominal:
            return f"l'analitzador la veu com a {self.token.pos} ({self.token.dep})"
        if self.future:
            return "l'analitzador hi llegeix un futur"
        if self.verbal:
            return "l'analitzador la veu com a verb conjugat en funció verbal"
        return f"l'analitzador no la veu en funció verbal ({self.token.pos}, {self.token.dep})"


@dataclass(frozen=True, slots=True)
class PastSimpleEvidence:
    """Resultat de combinar totes les fonts sobre una forma."""

    form: str
    verdict: Verdict
    infinitive: str | None = None
    auxiliary: str | None = None
    sources: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    parser_agrees: bool | None = None
    """Cert/fals si l'analitzador s'ha pogut pronunciar; ``None`` si no."""
    parser_verbal: bool = False
    """Cert si l'analitzador etiqueta la forma com a verb (encara que no en funció verbal)."""

    @property
    def accepted(self) -> bool:
        return self.verdict is Verdict.VERB

    @property
    def periphrastic(self) -> str | None:
        """«va infinitiu» si la forma s'accepta com a passat simple."""
        if not self.accepted or self.infinitive is None or self.auxiliary is None:
            return None
        return f"{self.auxiliary} {self.infinitive}"

    def describe(self) -> str:
        """Explicació en una línia, per a les notes del resultat i la depuració."""
        reasons = "; ".join(self.reasons) or "cap font no hi diu res"
        return f"«{self.form}»: {self.verdict.value} ({reasons})"


def lexical_readings(morphology: MorphologyProvider, form: str) -> LexicalReadings:
    """Lectures de coneixement lèxic d'una forma (l'endevinador no hi compta)."""
    entries = tuple(
        entry
        for entry in morphology.analyze(form)
        if entry.source != GUESSER_SOURCE and entry.confidence >= LEXICAL_MIN_CONFIDENCE
    )
    if not entries:
        return LexicalReadings(False)
    past: list[LexicalEntry] = []
    other_verb: list[LexicalEntry] = []
    non_verb: list[LexicalEntry] = []
    for entry in entries:
        features = entry.features
        if features.pos in ("verb", "aux"):
            if features.tense == "past" and features.mood in ("ind", None):
                past.append(entry)
            else:
                other_verb.append(entry)
        else:
            non_verb.append(entry)
    return LexicalReadings(True, tuple(past), tuple(other_verb), tuple(non_verb))


def knows_infinitive(morphology: MorphologyProvider, infinitive: str) -> bool | None:
    """Cert/fals si el recurs sap si l'infinitiu existeix; ``None`` si no té diccionari.

    Es comprova amb un infinitiu corrent: si el recurs no coneix ni «parlar»,
    no té cap diccionari de verbs i no pot dir res.
    """
    if not _lexical(morphology.analyze("parlar")):
        return None
    return any(
        entry.features.pos in ("verb", "aux") and entry.features.mood == "inf"
        for entry in _lexical(morphology.analyze(infinitive))
    )


def _resolve_auxiliary(past: tuple[LexicalEntry, ...]) -> tuple[str, str] | None:
    """Infinitiu i auxiliar de la lectura de passat: la tercera persona té prioritat.

    «decidí» és alhora primera i tercera persona del singular; la lectura que
    admet «va decidir» és la tercera, i és la que es fa servir.
    """
    ordered = sorted(past, key=lambda e: (e.features.person != "3", e.features.person or ""))
    for entry in ordered:
        auxiliary = AUXILIARIES.get((entry.features.person or "3", entry.features.number or "sg"))
        if auxiliary is not None:
            return entry.lemma, auxiliary
    return None


def _guessed_future(form: str) -> bool:
    """Cert si l'endevinador per sufixos llegeix la forma com un futur."""
    return any(
        entry.features.pos == "verb" and entry.features.tense == "fut" for entry in guess(form)
    )


def _lexical(entries: tuple[LexicalEntry, ...]) -> tuple[LexicalEntry, ...]:
    return tuple(
        e for e in entries if e.source != GUESSER_SOURCE and e.confidence >= LEXICAL_MIN_CONFIDENCE
    )


def parser_view(analysis: SentenceSyntax | None, offset: int) -> ParserView | None:
    """Vista de l'analitzador sobre el mot que hi ha a ``offset``, si se'n refia."""
    if analysis is None or not analysis.confident:
        return None
    token = analysis.token_at(offset)
    if token is None:
        return None
    by_index = {t.index: t for t in analysis.tokens}
    head = by_index.get(token.head, token)
    finite = token.pos in PREDICATE_POS and (token.verb_form == "Fin" or token.mood in FINITE_MOODS)
    coordinated_with_nominal = token.dep == "conj" and head.pos not in PREDICATE_POS
    nominal = token.pos in NOMINAL_POS or token.dep in NOMINAL_DEPS or coordinated_with_nominal
    verbal = finite and token.dep in CLAUSAL_DEPS and not nominal
    return ParserView(token, head, verbal=verbal, nominal=nominal, future=token.tense == "fut")


def assess_past_simple(
    form: str,
    *,
    morphology: MorphologyProvider,
    analysis: SentenceSyntax | None,
    offset: int,
    irregular: tuple[str, str] | None,
    regular: tuple[str, str] | None,
    plural_ending: bool,
    clitic_before: bool,
    capitalized_inside: bool,
) -> PastSimpleEvidence:
    """Decideix si ``form`` és un passat simple que es pot fer perifràstic.

    ``irregular`` i ``regular`` són ``(infinitiu, auxiliar)`` segons la taula
    d'irregulars i segons les terminacions, o ``None`` si no hi encaixen.
    ``plural_ending`` diu si la terminació és de plural («-aren», «-iren»...),
    molt més específica que la de singular. ``clitic_before`` diu si un pronom
    feble segur precedeix immediatament la forma, i ``capitalized_inside`` si
    la forma va en majúscula sense ser a l'inici de frase (un nom propi).
    """
    reasons: list[str] = []
    sources: list[str] = []
    readings = lexical_readings(morphology, form)
    view = parser_view(analysis, offset)
    parser_verbal = view is not None and view.token.pos in PREDICATE_POS
    parser_agrees: bool | None = None
    if view is not None:
        parser_agrees = view.verbal and not view.future

    def done(
        verdict: Verdict,
        infinitive: str | None = None,
        auxiliary: str | None = None,
        agrees: bool | None = parser_agrees,
    ) -> PastSimpleEvidence:
        return PastSimpleEvidence(
            form,
            verdict,
            infinitive,
            auxiliary,
            tuple(sources),
            tuple(reasons),
            agrees,
            parser_verbal,
        )

    if capitalized_inside:
        reasons.append("va en majúscula dins de la frase: un nom propi")
        return done(Verdict.NOT_VERB)

    # -- 1. El recurs coneix la forma: la seva lectura mana sobre la terminació. --------
    if readings.known:
        sources.append("morfologia")
        if not readings.past_verb:
            if readings.other_verb and not readings.non_verb:
                reasons.append("la morfologia hi veu un verb, però no de passat")
            else:
                reasons.append(f"la morfologia només hi veu {readings.describe_non_verb()}")
            if parser_verbal and view is not None:
                sources.append("analitzador")
                reasons.append("tot i que " + view.describe())
            return done(Verdict.NOT_VERB)
        resolved = _resolve_auxiliary(readings.past_verb)
        if resolved is None:
            reasons.append(
                "la lectura verbal de passat no és de tercera persona ni de primera o "
                "segona del plural"
            )
            return done(Verdict.NOT_VERB)
        infinitive, auxiliary = resolved
        if readings.only_past_verb:
            reasons.append("la morfologia només hi veu un verb de passat")
            if view is not None:
                sources.append("analitzador")
                reasons.append(view.describe())
            return done(Verdict.VERB, infinitive, auxiliary)
        # Ambigua: verb de passat o nom/adjectiu. Cal que el context ho resolgui.
        reasons.append(
            f"la morfologia hi veu un verb de passat i també {readings.describe_non_verb()}"
        )
        if view is not None:
            sources.append("analitzador")
            reasons.append(view.describe())
            if view.verbal and not view.future:
                return done(Verdict.VERB, infinitive, auxiliary, True)
            if view.nominal or view.future:
                return done(Verdict.NOT_VERB, agrees=False)
        if clitic_before:
            sources.append("pronom feble")
            reasons.append("un pronom feble segur la precedeix")
            return done(Verdict.VERB, infinitive, auxiliary)
        reasons.append("cap font no resol l'ambigüitat")
        return done(Verdict.AMBIGUOUS)

    # -- 2. El recurs no la coneix: taula d'irregulars i terminacions. ---------------------
    if irregular is None and _guessed_future(form):
        # L'endevinador per sufixos no serveix per afirmar res, però sí per
        # descartar: «-arà», «-irà», «-erà» són de futur, mai de passat simple.
        sources.append("terminació")
        reasons.append("la terminació és de futur, no de passat simple")
        return done(Verdict.NOT_VERB)
    if view is not None:
        sources.append("analitzador")
        reasons.append(view.describe())
        if view.future:
            return done(Verdict.NOT_VERB, agrees=False)
    if irregular is not None:
        infinitive, auxiliary = irregular
        sources.append("taula d'irregulars")
        reasons.append("és a la taula de passats simples irregulars")
        if view is not None and view.nominal:
            return done(Verdict.NOT_VERB, agrees=False)
        return done(Verdict.VERB, infinitive, auxiliary)
    if regular is None:
        return done(Verdict.UNKNOWN)
    infinitive, auxiliary = regular
    sources.append("terminació")
    known = knows_infinitive(morphology, infinitive)
    if known is False:
        reasons.append(f"el recurs morfològic no coneix cap verb «{infinitive}»")
        return done(Verdict.NOT_VERB)
    if view is not None and view.nominal:
        return done(Verdict.NOT_VERB, agrees=False)
    if plural_ending:
        reasons.append("terminació de plural pròpia del passat simple")
        return done(Verdict.VERB, infinitive, auxiliary)
    if view is not None and view.verbal:
        reasons.append("terminació de singular confirmada per l'analitzador")
        return done(Verdict.VERB, infinitive, auxiliary, True)
    if clitic_before:
        sources.append("pronom feble")
        reasons.append("terminació de singular amb un pronom feble segur al davant")
        return done(Verdict.VERB, infinitive, auxiliary)
    reasons.append("terminació de singular sense cap altra evidència: pot ser un nom o un adjectiu")
    return done(Verdict.AMBIGUOUS)


__all__ = [
    "AUXILIARIES",
    "CLAUSAL_DEPS",
    "NOMINAL_DEPS",
    "NOMINAL_POS",
    "LexicalReadings",
    "ParserView",
    "PastSimpleEvidence",
    "Verdict",
    "assess_past_simple",
    "knows_infinitive",
    "lexical_readings",
    "parser_view",
]
