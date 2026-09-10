"""Informe llegible d'una empremta: què s'hi ha fet servir i què val cada part.

L'informe respon quatre preguntes que la xifra sola no respon:

* **Amb què s'ha fet.** Documents, paraules, quins textos s'han exclòs i per
  què —els duplicats a part, perquè no són cap error de l'usuari sinó una
  decisió del carregador.
* **Què s'ha pogut analitzar.** Frases analitzades sintàcticament i frases
  descartades, i amb quin model s'han analitzat. Una empremta feta sense el
  parser no és pitjor: és una altra cosa, i es diu.
* **Quant se'n pot refiar.** La confiança de cada component. És un
  **indicador intern** derivat del nombre d'observacions i de documents, no
  cap probabilitat estadística demostrada, i l'informe ho diu cada vegada.
* **Si s'ha comprovat amb text de fora.** La validació independent distingeix
  «no hi ha prou dades» de «l'estil hi coincideix poc»: amb quatre frases
  reservades, una distància alta no vol dir res.

L'informe també diu que a l'empremta **hi ha fragments literals del corpus**
(curts, i limitats per configuració): no s'hi guarden només recomptes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from parafrasi_cat.style.fingerprint import StyleFingerprint, is_stat
from parafrasi_cat.style.profiler import (
    VALIDATION_CONSISTENT,
    VALIDATION_DIVERGENT,
    VALIDATION_INSUFFICIENT,
    validation_verdict,
)

#: Components amb una estadística representativa: la que en dona la confiança.
COMPONENTS: tuple[tuple[str, str], ...] = (
    ("longitud de frase", "sentence_length"),
    ("longitud de paràgraf", "paragraph_length_sentences"),
    ("comes", "punctuation.comma.per_100_words"),
    ("connectors", "connectors.per_100_words"),
    ("impersonals", "impersonal.per_100_sentences"),
    ("primera persona", "first_person.singular.per_100_sentences"),
    ("passives", "passive.per_100_sentences"),
    ("repetició lèxica", "lexical_repetition.type_token_ratio"),
    ("classes de mots", "word_class_density.verbs_per_100_words"),
)

CONFIDENCE_NOTE = (
    "indicador intern derivat d'observacions i documents, no cap probabilitat estadística"
)

#: Claus on es desen fragments literals del corpus.
EXAMPLE_KEYS: tuple[str, ...] = ("examples", "example", "ambiguous_examples")

_VERDICT_TEXT = {
    VALIDATION_INSUFFICIENT: (
        "sense dades suficients: amb tan poc text reservat la distància no en decideix res"
    ),
    VALIDATION_CONSISTENT: "el text reservat coincideix amb l'empremta",
    VALIDATION_DIVERGENT: "estil poc coincident: el text reservat s'aparta de l'empremta",
}

NO_VALIDATION = (
    "sense validació independent: no s'ha reservat cap text per comprovar l'estabilitat "
    "de l'empremta («style build … --validation DIR»)"
)


def count_example_fragments(node: object) -> int:
    """Fragments literals del corpus desats a l'empremta."""
    total = 0
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in EXAMPLE_KEYS:
                total += _count_fragments(value)
            else:
                total += count_example_fragments(value)
    elif isinstance(node, list):
        total += sum(count_example_fragments(item) for item in node)
    return total


def _count_fragments(value: object) -> int:
    if isinstance(value, str):
        return 1 if value else 0
    if isinstance(value, list):
        return sum(1 for item in value if isinstance(item, str) and item)
    return 0


def count_stats(node: object) -> int:
    """Característiques numèriques de l'empremta (objectes «stat»)."""
    if isinstance(node, Mapping):
        if is_stat(node):
            return 1
        return sum(count_stats(value) for value in node.values())
    if isinstance(node, list):
        return sum(count_stats(item) for item in node)
    return 0


def corpus_lines(fingerprint: StyleFingerprint, *, max_excluded: int = 6) -> list[str]:
    """Documents i paraules del corpus, i els textos que no hi han entrat."""
    corpus = fingerprint.corpus
    lines: list[str] = []
    corpus_type = corpus.get("type")
    if isinstance(corpus_type, str) and corpus_type:
        lines.append(f"  mena de corpus: {corpus_type}")
    lines.append(
        f"  documents: {corpus.get('n_documents')} · paràgrafs: {corpus.get('n_paragraphs')} · "
        f"frases: {corpus.get('n_sentences')} · paraules: {corpus.get('n_words')}"
    )
    excluded = corpus.get("excluded")
    if not isinstance(excluded, list) or not excluded:
        return lines
    duplicates = [e for e in excluded if isinstance(e, Mapping) and e.get("duplicate_of")]
    tail = f" ({len(duplicates)} per contingut repetit)" if duplicates else ""
    lines.append(f"  textos exclosos: {len(excluded)}{tail}")
    lines.extend(_excluded_lines(excluded, max_excluded))
    return lines


def _excluded_lines(excluded: Sequence[object], limit: int) -> list[str]:
    lines = [
        f"    · {entry.get('name')}: {entry.get('reason')}"
        for entry in excluded[:limit]
        if isinstance(entry, Mapping)
    ]
    if len(excluded) > limit:
        lines.append(f"    · … i {len(excluded) - limit} més")
    return lines


def syntax_lines(fingerprint: StyleFingerprint) -> list[str]:
    """Frases analitzades i descartades pel parser, i quin model s'ha fet servir."""
    profile = fingerprint.get("syntactic_profile")
    if not isinstance(profile, Mapping):
        return ["  sintaxi: l'empremta no porta perfil sintàctic"]
    if profile.get("available") is not True:
        reason = profile.get("reason") or "no disponible"
        return [f"  sintaxi: sense perfil ({reason})"]
    analysed = profile.get("sample_size_sentences", 0)
    skipped = profile.get("skipped_sentences", 0)
    parser = fingerprint.generator.get("parser") or "parser desconegut"
    return [
        f"  model sintàctic: {parser} (només analitza; no genera res)",
        f"  frases analitzades: {analysed} · descartades per anàlisi poc fiable: {skipped}"
        f" · confiança {profile.get('confidence')}",
    ]


def confidence_lines(
    fingerprint: StyleFingerprint, components: Iterable[tuple[str, str]] = COMPONENTS
) -> list[str]:
    """Confiança de cada component, amb la reserva que és un indicador intern."""
    parts = []
    for label, path in components:
        stat = fingerprint.stat(path)
        if stat is None:
            continue
        state = "sense dades" if stat.n_observations == 0 else f"{stat.confidence:.2f}"
        parts.append(f"{label} {state}")
    if not parts:
        return []
    lines = [f"  confiança per component ({CONFIDENCE_NOTE}):"]
    lines.extend(f"    {part}" for part in _wrap(parts))
    return lines


def _wrap(parts: Sequence[str], per_line: int = 3) -> list[str]:
    return [" · ".join(parts[i : i + per_line]) for i in range(0, len(parts), per_line)]


def content_lines(fingerprint: StyleFingerprint) -> list[str]:
    """Què conté l'empremta: recomptes i, també, fragments literals del corpus."""
    fragments = count_example_fragments(fingerprint.features)
    stats = count_stats(fingerprint.features)
    if not fragments:
        return [f"  contingut: {stats} característiques numèriques, sense cap fragment del corpus"]
    return [
        f"  contingut: {stats} característiques numèriques i {fragments} fragments literals "
        "del corpus (exemples curts que il·lustren cada tret; no són només recomptes)",
    ]


def validation_lines(fingerprint: StyleFingerprint) -> list[str]:
    """Resultat de la validació independent, o el fet que no n'hi ha."""
    validation = fingerprint.validation
    if validation is None:
        return [f"  {NO_VALIDATION}"]
    distance = validation.get("distance")
    n_sentences = validation.get("n_sentences", 0)
    n_documents = validation.get("n_documents", 0)
    if not isinstance(distance, int | float):
        return ["  validació: dades incompletes"]
    threshold = validation.get("divergence_threshold")
    verdict = validation.get("verdict")
    level = validation.get("confidence")
    if not isinstance(verdict, str) or verdict not in _VERDICT_TEXT:
        # Empremtes anteriors al veredicte: es dedueix dels recomptes que sí que hi ha.
        verdict, level = validation_verdict(
            int(n_sentences) if isinstance(n_sentences, int) else 0,
            int(n_documents) if isinstance(n_documents, int) else 0,
            float(distance),
            float(threshold) if isinstance(threshold, int | float) else 0.4,
        )
    lines = [
        f"  validació independent: {n_documents} documents, {n_sentences} frases, "
        f"distància {float(distance):.3f} (confiança {level})",
        f"    {_VERDICT_TEXT[verdict]}",
    ]
    divergent = validation.get("divergent_features")
    if verdict == VALIDATION_DIVERGENT and isinstance(divergent, list) and divergent:
        lines.append(f"    trets que s'aparten: {', '.join(str(d) for d in divergent[:5])}")
    return lines


def fingerprint_report(fingerprint: StyleFingerprint, *, header: str = "") -> str:
    """Informe complet: corpus, exclusions, sintaxi, confiança, contingut i validació."""
    lines = [header] if header else []
    lines.extend(corpus_lines(fingerprint))
    lines.extend(syntax_lines(fingerprint))
    lines.extend(confidence_lines(fingerprint))
    lines.extend(content_lines(fingerprint))
    lines.extend(validation_lines(fingerprint))
    return "\n".join(lines)


__all__ = [
    "COMPONENTS",
    "CONFIDENCE_NOTE",
    "EXAMPLE_KEYS",
    "NO_VALIDATION",
    "confidence_lines",
    "content_lines",
    "corpus_lines",
    "count_example_fragments",
    "count_stats",
    "fingerprint_report",
    "syntax_lines",
    "validation_lines",
]
