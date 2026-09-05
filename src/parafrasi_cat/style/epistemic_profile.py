"""Perfil epistemològic d'un autor: com marca evidència, inferència, hipòtesi i limitació.

Es calcula sobre el corpus de l'empremta amb el mateix lexicó epistemològic
que fa servir el validador, i només conserva recomptes: quants marcadors de
cada categoria per cent frases, quines formes fa servir més (el marcador
*preferit* de cada categoria), amb quina freqüència acumula dos marcadors de
prudència l'un al costat de l'altre (doble modalització), quina part de les
frases no porta cap marcador (formulació directa) i quina part dels marcadors
són explícits. No es desa cap frase del corpus.

El llenguatge assertiu fa servir el marcador preferit per categoria per triar,
a igual força, la formulació que l'autor mateix escriuria. La confiança depèn
de la mostra: amb menys de :data:`LOW_SAMPLE` marcadors el perfil no s'usa.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from parafrasi_cat.analyzer.analysis import Analyzer
from parafrasi_cat.analyzer.lexicon import normalize_form
from parafrasi_cat.validation.categories import EpistemicCategory
from parafrasi_cat.validation.epistemic import EpistemicLexicon

#: Marcadors mínims perquè el perfil sigui «medium» i «high».
LOW_SAMPLE = 10
HIGH_SAMPLE = 30
#: Distància màxima (caràcters) entre dos marcadors de prudència perquè siguin doble modalització.
REDUNDANCY_GAP = 32
#: Formes conservades per categoria (les més freqüents).
TOP_FORMS = 8

_HEDGING = (EpistemicCategory.HYPOTHESIS, EpistemicCategory.INFERENCE)


def epistemic_profile(
    texts: Iterable[str], analyzer: Analyzer, lexicon: EpistemicLexicon
) -> dict[str, object]:
    """Perfil epistemològic (només recomptes) dels textos indicats."""
    n_sentences = 0
    n_markers = 0
    n_explicit = 0
    direct = 0
    double = 0
    counts: Counter[EpistemicCategory] = Counter()
    forms: dict[EpistemicCategory, Counter[str]] = {c: Counter() for c in EpistemicCategory}
    for text in texts:
        for sentence in analyzer.analyze(text).sentences:
            n_sentences += 1
            profile = lexicon.profile(sentence.text)
            counted = [m for m in profile.matches if lexicon.class_of(m.class_id).counted]
            if not counted:
                direct += 1
                continue
            for match in counted:
                n_markers += 1
                counts[match.category] += 1
                forms[match.category][normalize_form(match.text)] += 1
                if match.explicit:
                    n_explicit += 1
            hedging = [m for m in counted if m.category in _HEDGING]
            for first, second in zip(hedging, hedging[1:], strict=False):
                if second.span.start - first.span.end <= REDUNDANCY_GAP:
                    double += 1
    if n_sentences == 0:
        return {"available": False, "reason": "cap frase al corpus"}
    per_100 = 100.0 / n_sentences
    categories: dict[str, object] = {}
    for category in EpistemicCategory:
        if category is EpistemicCategory.UNKNOWN:
            continue
        top = forms[category].most_common(TOP_FORMS)
        categories[category.value] = {
            "count": counts[category],
            "per_100_sentences": round(counts[category] * per_100, 2),
            "preferred": top[0][0] if top else None,
            "markers": dict(top),
        }
    if n_markers < LOW_SAMPLE:
        confidence = "low"
    elif n_markers < HIGH_SAMPLE:
        confidence = "medium"
    else:
        confidence = "high"
    modal = counts[EpistemicCategory.HYPOTHESIS] + counts[EpistemicCategory.INFERENCE]
    return {
        "available": True,
        "sample_size_sentences": n_sentences,
        "n_markers": n_markers,
        "confidence": confidence,
        "modal_density_per_100_sentences": round(modal * per_100, 2),
        "double_hedging_per_100_sentences": round(double * per_100, 2),
        "direct_share": round(direct / n_sentences, 4),
        "explicit_share": round(n_explicit / n_markers, 4) if n_markers else 0.0,
        "categories": categories,
        "limitation_forms": dict(forms[EpistemicCategory.LIMITATION].most_common(TOP_FORMS)),
        "evidence_forms": dict(forms[EpistemicCategory.EVIDENCE].most_common(TOP_FORMS)),
    }


__all__ = ["HIGH_SAMPLE", "LOW_SAMPLE", "epistemic_profile"]
