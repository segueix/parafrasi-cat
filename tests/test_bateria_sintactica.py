"""Bateria de 20 frases noves passades pel motor amb el **parser real**.

Aquest fitxer no repeteix cap de les frases que van motivar les regles
(``test_dospunts_presentatius.py``, ``test_blocs_reflexius.py``): el vocabulari
i les construccions són uns altres. La pregunta és si el que s'hi va programar
generalitza o si només resolia aquells exemples.

Com es comprova
---------------
No s'hi exigeix cap redacció literal. De cada frase se'n declara:

* **què s'hi admet** (:data:`ESTRUCTURAL` o :data:`INTACTE`): si el motor hi ha
  de trobar almenys una alternativa estructural o si s'hi ha d'abstenir;
* **què no hi pot canviar mai**, i això val per a *totes* les frases i per a
  *tots* els candidats: la negació, la modalitat, les xifres i els nombres
  romans, els noms propis, l'abast dels quantificadors i les afirmacions
  d'identitat.

Els invariants es comproven candidat per candidat, no només sobre el que el
motor prefereix: un candidat dolent que no guanyi continua sent un candidat
dolent.

Aquests tests **necessiten el parser local** i s'ometen si no hi és: no s'hi
simula cap arbre. Els tests d'arbre construït a mà són a
``test_blocs_reflexius.py``, i s'hi diu.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import pytest

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import apply_mode

ESTRUCTURAL = "estructural"
"""El motor hi ha de trobar almenys una alternativa que reorganitzi la frase."""

INTACTE = "intacte"
"""El motor s'hi ha d'abstenir d'estructura: o no proposa res, o només variants
de superfície (lèxic, temps verbal) que no toquen l'arquitectura."""


@dataclass(frozen=True)
class Case:
    text: str
    expects: str
    why: str
    identifies: bool = False
    """Cert si la frase autoritza una afirmació d'identitat («X és Y»): només
    quan hi ha uns dos punts que identifiquen el sintagma anterior."""

    tags: tuple[str, ...] = field(default_factory=tuple)


# --- A. presentatius amb identificació després de dos punts ------------------------------------

GROUP_A = (
    Case(
        "Hi ha un instrument medieval que va desaparèixer aviat: el psalteri.",
        ESTRUCTURAL,
        "identificació neta: l'analitzador penja «psalteri» del sintagma presentat",
        identifies=True,
    ),
    Case(
        "Hi ha una moneda del 1702 que encara es conserva: el ral de vuit.",
        ESTRUCTURAL,
        "identificació amb data i verb pronominal",
        identifies=True,
        tags=("data", "pronominal"),
    ),
    Case(
        "Hi ha uns oficis que no tenen equivalent modern: els mestres d'aixa.",
        ESTRUCTURAL,
        "plural amb negació: la còpula ha de concordar i el «no» s'ha de conservar",
        identifies=True,
        tags=("negació", "plural"),
    ),
    Case(
        "Hi ha un tractat del segle XIII que cita moltes fonts: el Llibre de contemplació.",
        ESTRUCTURAL,
        "nombre romà i nom propi; la identificació s'hi absté perquè l'analitzador "
        "penja «Llibre» de «fonts» i no del tractat",
        identifies=True,
        tags=("romà", "nom propi"),
    ),
    Case(
        "Hi ha una pràctica que no sembla documentada enlloc: la juraderia.",
        ESTRUCTURAL,
        "negació i modalitat alhora; la identificació s'hi absté perquè «juraderia» "
        "no queda com a aposició",
        identifies=True,
        tags=("negació", "modalitat"),
    ),
)

# --- B. incisos amb verbs pronominals o reflexius ----------------------------------------------

GROUP_B = (
    Case(
        "El notari, quan es presenta, deixa constància de l'acte.",
        ESTRUCTURAL,
        "el pronom reflexiu viatja amb el verb i no bloqueja el moviment",
        tags=("pronominal",),
    ),
    Case(
        "El batlle, quan es queixa, no obté cap resposta immediata.",
        ESTRUCTURAL,
        "verb pronominal pur amb negació i quantificador «cap»",
        tags=("pronominal", "negació"),
    ),
    Case(
        "La confraria, quan es dissol, no reparteix els béns entre els membres.",
        ESTRUCTURAL,
        "reflexiu amb valor mitjà; hi ha també un complement desplaçable",
        tags=("pronominal", "negació"),
    ),
    Case(
        "El consell, quan es reuneix el 1412, no admet cap absència.",
        ESTRUCTURAL,
        "data dins de la subordinada: s'ha de moure amb ella",
        tags=("pronominal", "data", "negació"),
    ),
    Case(
        "L'arxiu, quan es va constituir al segle XVI, no tenia cap inventari.",
        ESTRUCTURAL,
        "article elidit i nombre romà; «arxiu» és el cas que el conjecturador "
        "llegia com un verb i deixava la frase al nivell 2",
        tags=("pronominal", "romà", "negació", "article elidit"),
    ),
)

# --- C. subordinades coordinades ---------------------------------------------------------------

GROUP_C = (
    Case(
        "El gremi, quan creix o quan es divideix, tampoc no altera els estatuts.",
        ESTRUCTURAL,
        "coordinació de temporals: s'han de moure totes dues o cap",
        tags=("coordinació", "negació"),
    ),
    Case(
        "La cort, quan es desplaça o quan s'atura, manté el mateix protocol.",
        ESTRUCTURAL,
        "coordinació de dos verbs pronominals, un amb apòstrof",
        tags=("coordinació", "pronominal"),
    ),
    Case(
        "El mercat, quan obre o quan tanca, no admet cap excepció.",
        ESTRUCTURAL,
        "coordinació sense pronoms: el cas de control del grup",
        tags=("coordinació", "negació"),
    ),
    Case(
        "El síndic, si intervé o si delega, sembla mantenir la mateixa posició.",
        ESTRUCTURAL,
        "condicionals coordinades amb modalitat al verb principal",
        tags=("coordinació", "modalitat"),
    ),
    Case(
        "La sentència, quan s'executa o quan es recorre, no canvia de redacció.",
        ESTRUCTURAL,
        "coordinació de dos pronominals amb negació al principal",
        tags=("coordinació", "pronominal", "negació"),
    ),
)

# --- D. casos ambigus: el motor s'hi ha d'estar -----------------------------------------------

GROUP_D = (
    Case(
        "Hi ha un manuscrit que ningú no ha editat: el Cançoner de Ripoll.",
        INTACTE,
        "el relatiu és complement directe, no subjecte: no es pot fer «un manuscrit no ha editat»",
        tags=("negació", "nom propi"),
    ),
    Case(
        "Hi ha una condició que cal complir: no arribar tard.",
        INTACTE,
        "l'analitzador hi posa dos subjectes per a «cal» («que» i «complir»): "
        "l'arbre es contradiu i no s'hi pot refiar",
        tags=("negació",),
    ),
    Case(
        "Hi ha dos períodes que convé distingir: el primer i el segon.",
        INTACTE,
        "els dos punts enumeren, no identifiquen; i el relatiu tampoc no és subjecte",
        tags=("enumeració",),
    ),
    Case(
        "L'informe, que la comissió va aprovar, el signa el president.",
        INTACTE,
        "el pronom «el» té l'antecedent fora del bloc: moure'l perdria el referent",
        tags=("pronom acusatiu", "article elidit"),
    ),
    Case(
        "El consell no es va reunir mai: sembla que ningú no en tenia constància.",
        INTACTE,
        "els dos punts introdueixen una explicació amb subjecte propi i modalitat: "
        "convertir-la en relativa del subjecte en canviaria l'abast",
        tags=("negació", "modalitat"),
    ),
)

BATTERY = GROUP_A + GROUP_B + GROUP_C + GROUP_D


def test_the_battery_has_twenty_new_sentences() -> None:
    assert len(BATTERY) == 20
    assert len({c.text for c in BATTERY}) == 20
    assert sum(1 for c in BATTERY if c.expects == ESTRUCTURAL) == 15
    assert sum(1 for c in BATTERY if c.expects == INTACTE) == 5


# --- invariants: què no pot canviar mai --------------------------------------------------------

NEGATIONS = frozenset({"no", "ni", "cap", "mai", "tampoc", "gens", "ningú", "res", "enlloc"})
MODALITY = frozenset(
    {
        "sembla", "semblen", "semblava", "semblaven", "pot", "poden", "podia", "podien",
        "podria", "podrien", "potser", "cal", "calia", "caldria", "deu", "deuen",
        "probablement", "possiblement", "aparentment",
    }
)  # fmt: skip

#: Perífrasi d'obligació. «Ha» tot sol no compta: «hi ha» és el presentatiu, i
#: treure'l és justament el que fa la regla.
_OBLIGATION = re.compile(
    r"\b(ha|han|havia|havien|haurà|hauran|hauria|haurien)\s+de\b", re.IGNORECASE
)
UNIVERSAL = frozenset({"tot", "tots", "tota", "totes", "cada", "qualsevol", "sempre", "tothom"})
COPULAS = frozenset({"és", "són", "era", "eren", "fou", "foren", "constitueix", "constitueixen"})

TYPOGRAPHIC_APOSTROPHE = "\u2019"
"""Apòstrof tipogràfic: al text pot venir així, i compta com a apòstrof."""

_WORD = re.compile(r"[\w'" + TYPOGRAPHIC_APOSTROPHE + r"]+", re.UNICODE)
_ROMAN = re.compile(r"^[IVXLCDM]{2,}$")
_FIGURE = re.compile(r"\d+")


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def _fold(word: str) -> str:
    """Minúscula sense accents: per comparar «Sembla» amb «sembla»."""
    lowered = word.lower().replace(TYPOGRAPHIC_APOSTROPHE, "'")
    return "".join(c for c in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(c))


def negations(text: str) -> Counter[str]:
    return Counter(w for w in map(_fold, words(text)) if w in {_fold(n) for n in NEGATIONS})


def modality(text: str) -> Counter[str]:
    found = Counter(w for w in map(_fold, words(text)) if w in {_fold(m) for m in MODALITY})
    found["obligació"] = len(_OBLIGATION.findall(text))
    return +found  # sense les entrades a zero


def figures(text: str) -> Counter[str]:
    """Xifres i nombres romans, tal com són: no s'hi normalitza res."""
    found = Counter(_FIGURE.findall(text))
    found.update(w for w in words(text) if _ROMAN.match(w))
    return found


def proper_names(text: str) -> Counter[str]:
    """Mots en majúscula que no obren la frase ni són nombres romans."""
    found: Counter[str] = Counter()
    for match in _WORD.finditer(text):
        word = match.group()
        if not word[:1].isupper() or _ROMAN.match(word):
            continue
        before = text[: match.start()].rstrip()
        if not before or before.endswith((".", ":", "!", "?")):
            continue  # inici de frase o darrere de dos punts: la majúscula hi és de posició
        found[word] += 1
    return found


def universals(text: str) -> Counter[str]:
    return Counter(w for w in map(_fold, words(text)) if w in {_fold(u) for u in UNIVERSAL})


def copulas(text: str) -> Counter[str]:
    return Counter(w for w in map(_fold, words(text)) if w in {_fold(c) for c in COPULAS})


def check_invariants(case: Case, candidate: str) -> list[str]:
    """Tot allò que el candidat hauria hagut de conservar i no ha conservat."""
    problems: list[str] = []
    if negations(candidate) != negations(case.text):
        problems.append(f"canvia la negació: {negations(case.text)} → {negations(candidate)}")
    if modality(candidate) != modality(case.text):
        problems.append(f"canvia la modalitat: {modality(case.text)} → {modality(candidate)}")
    if figures(candidate) != figures(case.text):
        problems.append(f"canvia les xifres: {figures(case.text)} → {figures(candidate)}")
    if proper_names(candidate) != proper_names(case.text):
        problems.append(
            f"canvia els noms propis: {proper_names(case.text)} → {proper_names(candidate)}"
        )
    added = universals(candidate) - universals(case.text)
    if added:
        problems.append(f"introdueix un quantificador universal: {sorted(added)}")
    if copulas(candidate) - copulas(case.text) and not case.identifies:
        problems.append("afirma una identitat que la frase original no autoritza")
    return problems


def test_the_invariants_catch_what_they_are_for() -> None:
    """Els detectors no són decoratius: es comproven amb canvis fabricats."""
    case = GROUP_B[1]  # «El batlle, quan es queixa, no obté cap resposta immediata.»
    assert check_invariants(case, case.text) == []
    assert any("negació" in p for p in check_invariants(case, case.text.replace("no obté", "obté")))
    assert any("universal" in p for p in check_invariants(case, case.text.replace("cap", "tota")))
    dated = GROUP_B[3]
    assert any("xifres" in p for p in check_invariants(dated, dated.text.replace("1412", "1413")))
    roman = GROUP_A[3]
    assert any("xifres" in p for p in check_invariants(roman, roman.text.replace("XIII", "XIV")))
    modal = GROUP_A[4]
    assert any(
        "modalitat" in p for p in check_invariants(modal, modal.text.replace("no sembla", "no és"))
    )
    named = GROUP_D[0]
    assert any(
        "noms propis" in p
        for p in check_invariants(named, named.text.replace("Cançoner", "Canconer"))
    )
    plain = GROUP_D[4]
    assert any(
        "identitat" in p
        for p in check_invariants(plain, plain.text.replace("sembla que", "és cert que"))
    )


# --- execució amb el parser real ---------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():  # type: ignore[no-untyped-def]
    pipeline = build_pipeline(apply_mode(PipelineConfig(rule_set="parafrasi"), "profund", 3))
    if not pipeline.syntax.available:
        pytest.skip("cal el parser local (scripts/install_parser.py): aquí no se simula cap arbre")
    return pipeline


@dataclass(frozen=True)
class Outcome:
    case: Case
    structural: tuple[str, ...]
    surface: tuple[str, ...]
    broken: tuple[str, ...]

    @property
    def abstains(self) -> bool:
        return not self.structural and not self.surface


def run_case(pipeline, case: Case) -> Outcome:  # type: ignore[no-untyped-def]
    result = pipeline.run(case.text)
    structural: list[str] = []
    surface: list[str] = []
    broken: list[str] = []
    for sentence in result.sentences:
        for scored in sentence.candidates:
            candidate = scored.candidate
            if candidate.is_identity:
                continue
            problems = check_invariants(case, candidate.text)
            if problems:
                broken.append(f"{candidate.text} — {'; '.join(problems)}")
            elif candidate.structural_families:
                structural.append(candidate.text)
            else:
                surface.append(candidate.text)
    return Outcome(case, tuple(structural), tuple(surface), tuple(broken))


@pytest.fixture(scope="module")
def outcomes(engine) -> tuple[Outcome, ...]:  # type: ignore[no-untyped-def]
    return tuple(run_case(engine, case) for case in BATTERY)


def test_no_candidate_breaks_an_invariant(outcomes: tuple[Outcome, ...]) -> None:
    """Cap candidat, guanyi o no, no pot tocar el que la frase afirma."""
    offenders = [(o.case.text, o.broken) for o in outcomes if o.broken]
    assert offenders == [], offenders


@pytest.mark.parametrize("case", GROUP_A + GROUP_B + GROUP_C, ids=lambda c: c.text[:40])
def test_the_engine_finds_a_structural_alternative(
    outcomes: tuple[Outcome, ...], case: Case
) -> None:
    outcome = next(o for o in outcomes if o.case is case)
    assert outcome.structural, f"cap alternativa estructural: {case.why}"


@pytest.mark.parametrize("case", GROUP_D, ids=lambda c: c.text[:40])
def test_the_engine_leaves_the_ambiguous_sentence_alone(
    outcomes: tuple[Outcome, ...], case: Case
) -> None:
    outcome = next(o for o in outcomes if o.case is case)
    assert not outcome.structural, f"no s'hi hauria d'haver tocat l'estructura: {case.why}"


def test_the_presentative_never_turns_an_existential_into_a_general_claim(
    outcomes: tuple[Outcome, ...],
) -> None:
    """«Hi ha X que...» no pot passar a dir-ho de tots els X."""
    for outcome in outcomes:
        if "hi ha" not in _fold(outcome.case.text):
            continue
        for text in outcome.structural + outcome.surface:
            assert not universals(text), text


def test_the_identification_only_appears_where_the_colon_licenses_it(
    outcomes: tuple[Outcome, ...],
) -> None:
    """Cap candidat no pot afirmar «X és Y» si la frase no ho identificava."""
    for outcome in outcomes:
        if outcome.case.identifies:
            continue
        for text in outcome.structural + outcome.surface:
            assert copulas(text) - copulas(outcome.case.text) == Counter(), text


def test_the_report_of_the_battery(outcomes: tuple[Outcome, ...]) -> None:
    """Recompte del que ha passat, perquè quedi al registre de la prova.

    No és cap percentatge de millora general: són vint frases triades.
    """
    with_structure = [o for o in outcomes if o.structural]
    only_surface = [o for o in outcomes if not o.structural and o.surface]
    abstained = [o for o in outcomes if o.abstains]
    broken = [o for o in outcomes if o.broken]
    print(
        f"\nBateria de {len(outcomes)} frases (parser real):"
        f"\n  amb alternativa estructural correcta: {len(with_structure)}"
        f"\n  només amb variants de superfície: {len(only_surface)}"
        f"\n  abstencions completes: {len(abstained)}"
        f"\n  transformacions incorrectes: {len(broken)}"
    )
    for outcome in outcomes:
        mark = "E" if outcome.structural else ("s" if outcome.surface else "-")
        print(f"  [{mark}] {outcome.case.text}")
        for text in outcome.structural[:2]:
            print(f"        → {text}")
    assert len(broken) == 0
    assert len(with_structure) == 15
    assert len(with_structure) + len(only_surface) + len(abstained) == len(outcomes)


# --- correccions concretes que la bateria va destapar ------------------------------------------


def test_a_noun_read_as_a_verb_no_longer_degrades_the_analysis(engine) -> None:  # type: ignore[no-untyped-def]
    """El conjecturador llegeix «arxiu» com un verb; el parser hi veu un nom.

    Comparar el nombre d'aquestes dues lectures és un error de categoria, i feia
    caure la frase al nivell 2. La comprovació entre noms, que és per a la qual
    serveix, s'ha de mantenir.
    """
    parsed = engine.syntax.parse(GROUP_B[4].text)
    assert parsed.confident, parsed.confidence.reasons

    from parafrasi_cat.syntax.analysis import assess_confidence

    tokens = parsed.tokens
    same_category = assess_confidence(tokens, numbers_of=lambda form, upos: frozenset({"pl"}))
    assert not same_category.confident
    assert any("morfologia" in reason for reason in same_category.reasons)


def test_the_elided_article_is_not_treated_as_an_acronym(engine) -> None:  # type: ignore[no-untyped-def]
    """«L'arxiu» al mig de la frase ha d'anar en minúscula; «XVI» i «UE», no."""
    result = engine.run(GROUP_B[4].text)
    texts = [c.candidate.text for s in result.sentences for c in s.candidates]
    assert any(t.startswith("Quan es va constituir al segle XVI, l'arxiu") for t in texts)
    assert not any("L'arxiu" in t[1:] for t in texts)
    assert all("XVI" in t for t in texts)


def test_a_verb_with_two_subjects_authorises_nothing(engine) -> None:  # type: ignore[no-untyped-def]
    """L'arbre es contradiu: cap de les dues lectures no és prou segura."""
    parsed = engine.syntax.parse(GROUP_D[1].text)
    relative = next(t for t in parsed.tokens if t.text == "que")
    verb = next(t for t in parsed.tokens if t.index == relative.head)
    others = [
        t for t in parsed.tokens if t.head == verb.index and t.dep.startswith(("nsubj", "csubj"))
    ]
    assert len(others) > 1, "aquest cas depèn que el model hi posi dos subjectes"
    assert not any(
        c.candidate.text.startswith("Una condició cal")
        for s in engine.run(GROUP_D[1].text).sentences
        for c in s.candidates
    )
