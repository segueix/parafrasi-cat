"""Endevinador morfològic per sufixos.

S'aplica només quan cap lexicó ni diccionari no coneix la forma. Les anàlisis
que produeix tenen una confiança baixa i porten ``source="guesser"``: són
hipòtesis basades en les terminacions regulars del català, no coneixement
lèxic. Un consumidor que necessiti certesa ha d'ignorar-les.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parafrasi_cat.morphology.features import LexicalEntry, MorphFeatures

SOURCE = "guesser"

#: Participis irregulars freqüents (masculí singular → lema).
IRREGULAR_PARTICIPLES: dict[str, str] = {
    "conegut": "conèixer",
    "reconegut": "reconèixer",
    "pogut": "poder",
    "volgut": "voler",
    "sabut": "saber",
    "tingut": "tenir",
    "vingut": "venir",
    "hagut": "haver",
    "begut": "beure",
    "rebut": "rebre",
    "cregut": "creure",
    "vist": "veure",
    "fet": "fer",
    "dit": "dir",
    "escrit": "escriure",
    "obert": "obrir",
    "mort": "morir",
    "pres": "prendre",
    "après": "aprendre",
    "entès": "entendre",
    "estès": "estendre",
    "cabut": "cabre",
    "valgut": "valer",
    "mogut": "moure",
    "plogut": "ploure",
    "temut": "témer",
    "perdut": "perdre",
    "venut": "vendre",
    "rigut": "riure",
    "viscut": "viure",
    "nascut": "néixer",
    "crescut": "créixer",
    "merescut": "merèixer",
    "dut": "dur",
    "cuit": "coure",
    "dolgut": "doldre",
    "sofert": "sofrir",
    "cobert": "cobrir",
    "ofert": "oferir",
    "omplert": "omplir",
    "complert": "complir",
    "establert": "establir",
    "tret": "treure",
    "sigut": "ser",
    "anat": "anar",
    "romàs": "romandre",
    "atès": "atendre",
    "admès": "admetre",
    "permès": "permetre",
    "promès": "prometre",
    "comès": "cometre",
    "emès": "emetre",
    "tramès": "trametre",
    "resolt": "resoldre",
    "absolt": "absoldre",
    "mòlt": "moldre",
    "fos": "fondre",
    "confós": "confondre",
    "respost": "respondre",
    "compost": "compondre",
    "clos": "cloure",
    "inclòs": "incloure",
    "exclòs": "excloure",
    "conclòs": "concloure",
    "extret": "extreure",
    "distret": "distreure",
    "contret": "contreure",
    "corregut": "córrer",
    "ocorregut": "ocórrer",
    "descobert": "descobrir",
    "encobert": "encobrir",
    "reobert": "reobrir",
    "constret": "constrènyer",
    "empès": "empènyer",
    "imprès": "imprimir",
    "encès": "encendre",
    "defès": "defendre",
    "ofès": "ofendre",
    "suspès": "suspendre",
    "despès": "despendre",
    "estret": "estrènyer",
    "pertangut": "pertànyer",
    "plangut": "plànyer",
    "fingit": "fingir",
    "obtingut": "obtenir",
    "contingut": "contenir",
    "mantingut": "mantenir",
    "sostingut": "sostenir",
    "detingut": "detenir",
    "retingut": "retenir",
    "esdevingut": "esdevenir",
    "convingut": "convenir",
    "previst": "preveure",
    "revist": "reveure",
    "entrevist": "entreveure",
    "desfet": "desfer",
    "refet": "refer",
    "satisfet": "satisfer",
    "contradit": "contradir",
    "predit": "predir",
    "descrit": "descriure",
    "inscrit": "inscriure",
    "prescrit": "prescriure",
    "transcrit": "transcriure",
    "subscrit": "subscriure",
    "sotmès": "sotmetre",
    "remès": "remetre",
    "omès": "ometre",
    "transmès": "transmetre",
    "compromès": "comprometre",
    "dissolt": "dissoldre",
    "absorbit": "absorbir",
}

_ACCENT_VARIANTS: dict[str, tuple[str, ...]] = {
    "e": ("è", "é"),
    "o": ("ò", "ó"),
    "a": ("à",),
    "i": ("í",),
    "u": ("ú",),
}

_WORD_RE = re.compile(r"^[^\W\d_]+$")


@dataclass(frozen=True, slots=True)
class _Rule:
    suffix: str
    lemma_suffix: str
    features: MorphFeatures
    confidence: float
    min_stem: int = 2
    note: str = ""


def _v(
    tense: str | None, mood: str, person: str | None = None, number: str | None = None
) -> MorphFeatures:
    return MorphFeatures(pos="verb", person=person, number=number, tense=tense, mood=mood)


#: Terminacions verbals prou distintives (ordenades: les més llargues primer).
_VERB_RULES: tuple[_Rule, ...] = (
    # participis regulars
    _Rule("ades", "ar", MorphFeatures(pos="verb", mood="part", gender="f", number="pl"), 0.5),
    _Rule("ada", "ar", MorphFeatures(pos="verb", mood="part", gender="f", number="sg"), 0.45),
    _Rule("ats", "ar", MorphFeatures(pos="verb", mood="part", gender="m", number="pl"), 0.45),
    _Rule("at", "ar", MorphFeatures(pos="verb", mood="part", gender="m", number="sg"), 0.4),
    _Rule("ides", "ir", MorphFeatures(pos="verb", mood="part", gender="f", number="pl"), 0.45),
    _Rule("ida", "ir", MorphFeatures(pos="verb", mood="part", gender="f", number="sg"), 0.4),
    _Rule("its", "ir", MorphFeatures(pos="verb", mood="part", gender="m", number="pl"), 0.35),
    _Rule("it", "ir", MorphFeatures(pos="verb", mood="part", gender="m", number="sg"), 0.3),
    _Rule(
        "udes",
        "re",
        MorphFeatures(pos="verb", mood="part", gender="f", number="pl"),
        0.35,
        note="lema -re o -er",
    ),
    _Rule(
        "uda",
        "re",
        MorphFeatures(pos="verb", mood="part", gender="f", number="sg"),
        0.3,
        note="lema -re o -er",
    ),
    _Rule(
        "uts",
        "re",
        MorphFeatures(pos="verb", mood="part", gender="m", number="pl"),
        0.3,
        note="lema -re o -er",
    ),
    _Rule(
        "ut",
        "re",
        MorphFeatures(pos="verb", mood="part", gender="m", number="sg"),
        0.3,
        note="lema -re o -er",
    ),
    # imperfet d'indicatiu (1a conjugació)
    _Rule("àvem", "ar", _v("impf", "ind", "1", "pl"), 0.6),
    _Rule("àveu", "ar", _v("impf", "ind", "2", "pl"), 0.6),
    _Rule("aven", "ar", _v("impf", "ind", "3", "pl"), 0.6),
    _Rule("aves", "ar", _v("impf", "ind", "2", "sg"), 0.5),
    _Rule("ava", "ar", _v("impf", "ind", None, "sg"), 0.55, note="1a o 3a persona"),
    # imperfet d'indicatiu (2a i 3a conjugació)
    _Rule("íem", "re", _v("impf", "ind", "1", "pl"), 0.5, note="lema -re, -er o -ir"),
    _Rule("íeu", "re", _v("impf", "ind", "2", "pl"), 0.5, note="lema -re, -er o -ir"),
    _Rule("ien", "re", _v("impf", "ind", "3", "pl"), 0.45, note="lema -re, -er o -ir"),
    _Rule(
        "ia", "re", _v("impf", "ind", None, "sg"), 0.35, note="1a o 3a persona; lema -re, -er o -ir"
    ),
    # futur
    _Rule("arem", "ar", _v("fut", "ind", "1", "pl"), 0.55),
    _Rule("areu", "ar", _v("fut", "ind", "2", "pl"), 0.55),
    _Rule("aran", "ar", _v("fut", "ind", "3", "pl"), 0.55),
    _Rule("aràs", "ar", _v("fut", "ind", "2", "sg"), 0.55),
    _Rule("arà", "ar", _v("fut", "ind", "3", "sg"), 0.55),
    _Rule("aré", "ar", _v("fut", "ind", "1", "sg"), 0.5),
    _Rule("irem", "ir", _v("fut", "ind", "1", "pl"), 0.55),
    _Rule("ireu", "ir", _v("fut", "ind", "2", "pl"), 0.55),
    _Rule("iran", "ir", _v("fut", "ind", "3", "pl"), 0.55),
    _Rule("iràs", "ir", _v("fut", "ind", "2", "sg"), 0.55),
    _Rule("irà", "ir", _v("fut", "ind", "3", "sg"), 0.55),
    _Rule("iré", "ir", _v("fut", "ind", "1", "sg"), 0.5),
    _Rule("rem", "re", _v("fut", "ind", "1", "pl"), 0.35, note="lema -re o -er"),
    _Rule("reu", "re", _v("fut", "ind", "2", "pl"), 0.35, note="lema -re o -er"),
    _Rule("ran", "re", _v("fut", "ind", "3", "pl"), 0.35, note="lema -re o -er"),
    _Rule("ràs", "re", _v("fut", "ind", "2", "sg"), 0.4, note="lema -re o -er"),
    _Rule("rà", "re", _v("fut", "ind", "3", "sg"), 0.4, note="lema -re o -er"),
    _Rule("ré", "re", _v("fut", "ind", "1", "sg"), 0.35, note="lema -re o -er"),
    # condicional
    _Rule("aríem", "ar", _v("cond", "ind", "1", "pl"), 0.6),
    _Rule("aríeu", "ar", _v("cond", "ind", "2", "pl"), 0.6),
    _Rule("arien", "ar", _v("cond", "ind", "3", "pl"), 0.6),
    _Rule("aries", "ar", _v("cond", "ind", "2", "sg"), 0.5),
    _Rule("aria", "ar", _v("cond", "ind", None, "sg"), 0.5, note="1a o 3a persona"),
    _Rule("iríem", "ir", _v("cond", "ind", "1", "pl"), 0.6),
    _Rule("iríeu", "ir", _v("cond", "ind", "2", "pl"), 0.6),
    _Rule("irien", "ir", _v("cond", "ind", "3", "pl"), 0.6),
    _Rule("iries", "ir", _v("cond", "ind", "2", "sg"), 0.5),
    _Rule("iria", "ir", _v("cond", "ind", None, "sg"), 0.5, note="1a o 3a persona"),
    _Rule("ríem", "re", _v("cond", "ind", "1", "pl"), 0.45, note="lema -re o -er"),
    _Rule("ríeu", "re", _v("cond", "ind", "2", "pl"), 0.45, note="lema -re o -er"),
    _Rule("rien", "re", _v("cond", "ind", "3", "pl"), 0.45, note="lema -re o -er"),
    _Rule("ries", "re", _v("cond", "ind", "2", "sg"), 0.35, note="lema -re o -er"),
    _Rule("ria", "re", _v("cond", "ind", None, "sg"), 0.35, note="1a o 3a persona; lema -re o -er"),
    # passat simple (1a conjugació)
    _Rule("àrem", "ar", _v("past", "ind", "1", "pl"), 0.55),
    _Rule("àreu", "ar", _v("past", "ind", "2", "pl"), 0.55),
    _Rule("aren", "ar", _v("past", "ind", "3", "pl"), 0.5),
    # imperfet de subjuntiu
    _Rule("éssim", "ar", _v("impf", "subj", "1", "pl"), 0.55),
    _Rule("éssiu", "ar", _v("impf", "subj", "2", "pl"), 0.55),
    _Rule("essin", "ar", _v("impf", "subj", "3", "pl"), 0.55),
    _Rule("essis", "ar", _v("impf", "subj", "2", "sg"), 0.5),
    _Rule("íssim", "ir", _v("impf", "subj", "1", "pl"), 0.55),
    _Rule("íssiu", "ir", _v("impf", "subj", "2", "pl"), 0.55),
    _Rule("issin", "ir", _v("impf", "subj", "3", "pl"), 0.55),
    _Rule("issis", "ir", _v("impf", "subj", "2", "sg"), 0.5),
    # present: 3a persona del plural i incoatius
    _Rule("eixen", "ir", _v("pres", "ind", "3", "pl"), 0.5),
    _Rule("eixes", "ir", _v("pres", "ind", "2", "sg"), 0.4),
    _Rule("eixo", "ir", _v("pres", "ind", "1", "sg"), 0.45),
    _Rule("eix", "ir", _v("pres", "ind", "3", "sg"), 0.3),
    _Rule(
        "en", "ar", _v("pres", "ind", "3", "pl"), 0.35, min_stem=3, note="lema -ar, -re, -er o -ir"
    ),
    _Rule("em", "ar", _v("pres", "ind", "1", "pl"), 0.3, min_stem=3, note="lema -ar, -re o -er"),
    _Rule("eu", "ar", _v("pres", "ind", "2", "pl"), 0.25, min_stem=3, note="lema -ar, -re o -er"),
    _Rule("im", "ir", _v("pres", "ind", "1", "pl"), 0.35, min_stem=3),
    _Rule("iu", "ir", _v("pres", "ind", "2", "pl"), 0.3, min_stem=3),
    # gerundis
    _Rule("ant", "ar", _v(None, "ger"), 0.3, min_stem=3),
    _Rule("int", "ir", _v(None, "ger"), 0.4, min_stem=3),
    # infinitius
    _Rule("ar", "ar", _v(None, "inf"), 0.4, min_stem=3),
    _Rule("ir", "ir", _v(None, "inf"), 0.4, min_stem=3),
    _Rule("re", "re", _v(None, "inf"), 0.3, min_stem=3),
    _Rule("er", "er", _v(None, "inf"), 0.3, min_stem=3),
)

_VERB_RULES = tuple(sorted(_VERB_RULES, key=lambda rule: -len(rule.suffix)))

_DIPHTHONG_RE = re.compile(r"[aeiou]u$")


def _lemma_for(stem: str, rule: _Rule) -> str:
    if rule.lemma_suffix in ("ar", "ir", "er", "re") and rule.suffix in ("ar", "ir", "er", "re"):
        return stem + rule.suffix
    if rule.suffix == "en" and _DIPHTHONG_RE.search(stem):
        return stem + "re"  # extreuen → extreure, creuen → creure
    if rule.suffix == "ia" and stem[-1] in "aeiou":
        return stem + "ure"  # creia → creure, veia → veure, treia → treure
    return stem + rule.lemma_suffix


def _irregular_participle(form: str) -> tuple[str, MorphFeatures] | None:
    """Reconeix participis irregulars, també en femení i plural."""
    candidates: list[tuple[str, str, str]] = [(form, "m", "sg")]
    for ending, gender, number in (
        ("os", "m", "pl"),
        ("es", "f", "pl"),
        ("s", "m", "pl"),
        ("a", "f", "sg"),
    ):
        if form.endswith(ending) and len(form) > len(ending) + 1:
            candidates.append((form[: -len(ending)], gender, number))
    for base, gender, number in candidates:
        for variant in _base_variants(base):
            lemma = IRREGULAR_PARTICIPLES.get(variant)
            if lemma is not None:
                return lemma, MorphFeatures(pos="verb", mood="part", gender=gender, number=number)
    return None


def _base_variants(base: str) -> list[str]:
    """Variants d'una base després de treure la desinència: ensordiment i accents."""
    variants = [base]
    if base.endswith("d"):
        variants.append(base[:-1] + "t")  # coneguda → conegut
    if base.endswith("s") and len(base) > 2:
        variants.append(base)  # presa → pres
    for candidate in list(variants):
        for index in range(len(candidate) - 1, -1, -1):
            char = candidate[index]
            if char in _ACCENT_VARIANTS:
                variants.extend(
                    candidate[:index] + accented + candidate[index + 1 :]
                    for accented in _ACCENT_VARIANTS[char]
                )
                break
    return variants


def guess(form: str) -> tuple[LexicalEntry, ...]:
    """Proposa anàlisis per a una forma desconeguda a partir de les terminacions."""
    lowered = form.lower()
    if not _WORD_RE.match(lowered) or len(lowered) < 3:
        return ()

    irregular = _irregular_participle(lowered)
    if irregular is not None:
        lemma, features = irregular
        return (LexicalEntry(form, lemma, features, confidence=0.7, source=SOURCE),)

    for rule in _VERB_RULES:
        if not lowered.endswith(rule.suffix):
            continue
        stem = lowered[: -len(rule.suffix)]
        if len(stem) < rule.min_stem:
            continue
        if rule.suffix == "ia" and (len(stem) < 2 or any(c in "àèéíòóúï" for c in stem)):
            continue  # gràcia, família, ciència: mot esdrúixol, la «i» no és desinència verbal
        return (
            LexicalEntry(
                form,
                _lemma_for(stem, rule),
                rule.features,
                confidence=rule.confidence,
                source=SOURCE,
            ),
        )

    return (_guess_nominal(form, lowered),)


def _guess_nominal(form: str, lowered: str) -> LexicalEntry:
    """Hipòtesi nominal molt feble: només nombre i, si de cas, gènere."""
    if lowered.endswith("es") and len(lowered) > 3:
        features = MorphFeatures(pos="noun", gender="f", number="pl")
        lemma = lowered[:-2] + "a"
    elif lowered.endswith("s") and len(lowered) > 2:
        features = MorphFeatures(pos="noun", number="pl")
        lemma = lowered[:-1]
    elif lowered.endswith("a"):
        features = MorphFeatures(pos="noun", gender="f", number="sg")
        lemma = lowered
    else:
        features = MorphFeatures(pos="noun", number="sg")
        lemma = lowered
    return LexicalEntry(form, lemma, features, confidence=0.2, source=SOURCE)
