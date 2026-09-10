"""Fiabilitat de l'empremta: duplicats, solapament de corpus i informe.

Tres coses que abans no es veien i ara sí:

1. **Duplicats per contingut.** Dos fitxers amb noms diferents i el mateix text
   comptaven dues vegades i inflaven el corpus. Ara el segon queda exclòs i es
   diu de quin document és còpia. La comparació normalitza només allò que no
   canvia res (final de línia, espai al final de línia, línies en blanc als
   extrems): un canvi de puntuació o de majúscules ja fa que siguin textos
   diferents.
2. **Solapament entre corpus.** Un text que és al corpus principal i al de
   validació es conserva al principal i s'exclou del de validació: si no, la
   validació confirmaria una empremta que aquell mateix text ha definit.
3. **Informe.** Diu amb què s'ha fet l'empremta, què s'ha pogut analitzar,
   quant se'n pot refiar cada component i si s'ha comprovat amb text de fora,
   distingint «sense dades suficients» de «estil poc coincident».

Cap fitxer original no es toca: excloure és no llegir-lo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parafrasi_cat.analyzer import ClosedClassLexicon, RuleBasedAnalyzer
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.style import (
    StyleFingerprint,
    StyleResources,
    build_fingerprint,
    load_corpus,
    normalized_text,
)
from parafrasi_cat.style.profiler import (
    VALIDATION_CONSISTENT,
    VALIDATION_DIVERGENT,
    VALIDATION_INSUFFICIENT,
    validation_verdict,
)
from parafrasi_cat.style.report import (
    NO_VALIDATION,
    content_lines,
    corpus_lines,
    count_example_fragments,
    fingerprint_report,
    syntax_lines,
    validation_lines,
)
from parafrasi_cat.style.schema import SCHEMA_FILE, load_schema, validate

TEXT = (
    "La reforma del sistema notarial va començar el 1387 i va durar tres dècades. "
    "Els documents conservats no permeten reconstruir-ne tots els passos.\n\n"
    "El veguer hi intervenia sovint, però la seva funció era subsidiària. "
    "Cap dels registres del segle XV no en detalla el procediment.\n"
)
OTHER = (
    "Els gremis de la ciutat mantenien registres propis des del 1350. "
    "La comparació amb els llibres reials mostra divergències notables.\n\n"
    "Cap inventari no és complet, i els que ho semblen són còpies tardanes. "
    "Els historiadors hi han vist un problema de transmissió, no de contingut.\n"
)


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / name
    file.write_text(text, encoding="utf-8")
    return file


# --- normalització: només allò que no canvia res ----------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        TEXT.replace("\n", "\r\n"),
        TEXT.replace("passos.\n", "passos.   \n"),  # espai al final de línia
        "\n\n" + TEXT + "\n\n",  # línies en blanc als extrems
    ],
)
def test_innocuous_differences_are_the_same_content(variant: str) -> None:
    assert normalized_text(variant) == normalized_text(TEXT)


@pytest.mark.parametrize(
    "variant",
    [
        TEXT.replace("1387", "1388"),  # una data
        TEXT.replace("no permeten", "permeten"),  # una negació
        TEXT.replace("La reforma", "la reforma"),  # una majúscula
        TEXT.replace("segle XV", "segle xv"),  # un nombre romà
        TEXT.replace("notarial va", "notarial  va"),  # espai interior
    ],
)
def test_a_meaningful_difference_is_another_document(variant: str) -> None:
    assert normalized_text(variant) != normalized_text(TEXT)


# --- duplicats dins d'un corpus ----------------------------------------------------------------


def test_a_duplicate_with_another_name_counts_once(tmp_path: Path) -> None:
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "z-copia.md", TEXT.replace("\n", "\r\n"))
    _write(main, "b.txt", OTHER)

    corpus = load_corpus(main)

    assert [d.name for d in corpus.documents] == ["a.txt", "b.txt"]
    assert [(e.name, e.duplicate_of) for e in corpus.duplicates] == [("z-copia.md", "a.txt")]
    assert "duplicat de «a.txt»" in corpus.duplicates[0].reason
    # El fitxer original hi continua sent: excloure és no llegir-lo.
    assert (main / "z-copia.md").is_file()


def test_the_first_by_name_is_the_one_kept(tmp_path: Path) -> None:
    """L'ordre és determinista: sempre es conserva el primer per nom relatiu."""
    main = tmp_path / "principal"
    _write(main, "zeta.txt", TEXT)
    _write(main, "alfa.txt", TEXT)

    corpus = load_corpus(main)

    assert [d.name for d in corpus.documents] == ["alfa.txt"]
    assert corpus.duplicates[0].name == "zeta.txt"
    assert corpus.duplicates[0].duplicate_of == "alfa.txt"


def test_a_text_that_differs_in_one_word_is_not_a_duplicate(tmp_path: Path) -> None:
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", TEXT.replace("tres dècades", "quatre dècades"))

    corpus = load_corpus(main)

    assert len(corpus.documents) == 2
    assert corpus.duplicates == ()


# --- solapament entre el corpus principal i el de validació -----------------------------------


def test_the_same_document_never_counts_in_both_corpora(tmp_path: Path) -> None:
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", OTHER)
    validation = tmp_path / "validacio"
    _write(validation, "reserva.txt", TEXT)  # el mateix text que a.txt

    corpus = load_corpus(main, validation_dir=validation)

    assert [d.name for d in corpus.main] == ["a.txt", "b.txt"]
    assert corpus.validation == ()
    overlap = corpus.duplicates[0]
    assert overlap.name == "validation/reserva.txt"
    assert overlap.duplicate_of == "a.txt"
    assert "no pot validar-se a si mateix" in overlap.reason


def test_the_main_corpus_is_the_one_that_keeps_the_document(tmp_path: Path) -> None:
    """No es perd cap text del corpus principal per haver-lo repetit a la validació."""
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    validation = tmp_path / "validacio"
    _write(validation, "a.txt", TEXT)
    _write(validation, "nou.txt", OTHER)

    corpus = load_corpus(main, validation_dir=validation)

    assert [d.name for d in corpus.main] == ["a.txt"]
    assert [d.name for d in corpus.validation] == ["validation/nou.txt"]


def test_a_duplicate_inside_the_validation_corpus_is_a_duplicate(tmp_path: Path) -> None:
    """Repetit dins de la validació: és un duplicat, no cap solapament."""
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    validation = tmp_path / "validacio"
    _write(validation, "u.txt", OTHER)
    _write(validation, "v.txt", OTHER)

    corpus = load_corpus(main, validation_dir=validation)

    assert [d.name for d in corpus.validation] == ["validation/u.txt"]
    excluded = corpus.duplicates[0]
    assert excluded.name == "validation/v.txt"
    assert "duplicat de «validation/u.txt»" in excluded.reason


# --- mena de corpus ----------------------------------------------------------------------------


def test_the_corpus_type_is_a_label_that_changes_no_count(tmp_path: Path) -> None:
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)

    plain = load_corpus(main)
    typed = load_corpus(main, corpus_type="prosa d'investigació")

    assert plain.corpus_type == ""
    assert typed.corpus_type == "prosa d'investigació"
    assert [d.text for d in plain.documents] == [d.text for d in typed.documents]


# --- l'empremta: recomptes, esquema i informe --------------------------------------------------


@pytest.fixture(scope="module")
def resources() -> tuple[StyleResources, RuleBasedAnalyzer]:
    paths = ProjectPaths.discover(None)
    lexicon = ClosedClassLexicon.load(paths.language())
    return StyleResources.load(paths, lexicon=lexicon), RuleBasedAnalyzer(lexicon=lexicon)


def _fingerprint(corpus, resources) -> StyleFingerprint:  # type: ignore[no-untyped-def]
    style, analyzer = resources
    return build_fingerprint(corpus, style, analyzer, name="prova")


def test_the_duplicate_does_not_inflate_the_word_count(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", OTHER)
    single = _fingerprint(load_corpus(main), resources)

    _write(main, "c-copia.txt", TEXT)
    with_copy = _fingerprint(load_corpus(main), resources)

    assert with_copy.corpus["n_documents"] == single.corpus["n_documents"] == 2
    assert with_copy.corpus["n_words"] == single.corpus["n_words"]
    assert with_copy.corpus["n_duplicates"] == 1
    assert single.corpus["n_duplicates"] == 0


def test_the_fingerprint_records_the_excluded_duplicate(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "copia.txt", TEXT)
    fingerprint = _fingerprint(load_corpus(main, corpus_type="prosa d'investigació"), resources)

    excluded = fingerprint.corpus["excluded"]
    assert isinstance(excluded, list) and len(excluded) == 1
    assert excluded[0]["duplicate_of"] == "a.txt"
    assert fingerprint.corpus["type"] == "prosa d'investigació"

    schema_file = ProjectPaths.discover(None).optional(SCHEMA_FILE)
    assert schema_file is not None
    assert validate(fingerprint.to_dict(), load_schema(schema_file)) == []


def test_the_report_names_the_excluded_documents(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "copia.txt", TEXT)
    fingerprint = _fingerprint(load_corpus(main, corpus_type="prosa d'investigació"), resources)

    lines = "\n".join(corpus_lines(fingerprint))

    assert "mena de corpus: prosa d'investigació" in lines
    assert "1 per contingut repetit" in lines
    assert "copia.txt" in lines and "duplicat de «a.txt»" in lines


def test_the_report_says_the_fingerprint_keeps_literal_fragments(
    tmp_path: Path,
    resources,  # type: ignore[no-untyped-def]
) -> None:
    """No són només recomptes: hi ha fragments curts del corpus, i cal dir-ho."""
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", OTHER)
    fingerprint = _fingerprint(load_corpus(main), resources)

    fragments = count_example_fragments(fingerprint.features)
    assert fragments > 0
    line = "\n".join(content_lines(fingerprint))
    assert f"{fragments} fragments literals" in line
    assert "no són només recomptes" in line


def test_a_fingerprint_without_the_parser_says_so(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    fingerprint = _fingerprint(load_corpus(main), resources)

    line = "\n".join(syntax_lines(fingerprint))

    assert line.startswith("  sintaxi: sense perfil")
    assert "parser" in line


# --- validació independent: dades insuficients vs estil poc coincident -------------------------


def test_no_validation_is_not_a_bad_result(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    fingerprint = _fingerprint(load_corpus(main), resources)

    assert fingerprint.validation is None
    assert validation_lines(fingerprint) == [f"  {NO_VALIDATION}"]


@pytest.mark.parametrize(
    ("n_sentences", "n_documents", "distance", "expected"),
    [
        (4, 1, 0.9, VALIDATION_INSUFFICIENT),  # distància alta, però no hi ha dades
        (4, 1, 0.0, VALIDATION_INSUFFICIENT),  # distància baixa, tampoc no en diu res
        (40, 2, 0.9, VALIDATION_DIVERGENT),
        (40, 2, 0.1, VALIDATION_CONSISTENT),
        (20, 1, 0.5, VALIDATION_DIVERGENT),
    ],
)
def test_the_verdict_separates_lack_of_data_from_divergence(
    n_sentences: int, n_documents: int, distance: float, expected: str
) -> None:
    verdict, _ = validation_verdict(n_sentences, n_documents, distance)
    assert verdict == expected


def test_a_small_validation_corpus_reports_insufficient_data(tmp_path: Path, resources) -> None:  # type: ignore[no-untyped-def]
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", OTHER)
    validation = tmp_path / "validacio"
    _write(validation, "v.txt", "Un sol document curt. I prou.\n")

    fingerprint = _fingerprint(load_corpus(main, validation_dir=validation), resources)

    assert fingerprint.validation is not None
    assert fingerprint.validation["verdict"] == VALIDATION_INSUFFICIENT
    line = "\n".join(validation_lines(fingerprint))
    assert "sense dades suficients" in line
    assert "estil poc coincident" not in line


def test_an_old_fingerprint_without_a_verdict_still_reports(
    tmp_path: Path,
    resources,  # type: ignore[no-untyped-def]
) -> None:
    """Compatibilitat: el veredicte es dedueix dels recomptes que ja hi eren."""
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    _write(main, "b.txt", OTHER)
    validation = tmp_path / "validacio"
    _write(validation, "v.txt", OTHER.replace("gremis", "consells"))
    fingerprint = _fingerprint(load_corpus(main, validation_dir=validation), resources)

    data = json.loads(fingerprint.to_json())
    data["validation"].pop("verdict")
    data["validation"].pop("confidence")
    data["corpus"].pop("n_duplicates", None)
    old = StyleFingerprint.from_dict(data)

    line = "\n".join(validation_lines(old))
    assert "validació independent" in line
    assert "sense dades suficients" in line or "coincideix" in line
    # I l'informe sencer no peta amb una empremta sense els camps nous.
    assert "documents:" in fingerprint_report(old)


def test_an_old_fingerprint_without_the_new_corpus_fields_still_validates(
    tmp_path: Path,
    resources,  # type: ignore[no-untyped-def]
) -> None:
    main = tmp_path / "principal"
    _write(main, "a.txt", TEXT)
    fingerprint = _fingerprint(load_corpus(main), resources)
    data = json.loads(fingerprint.to_json())
    data["corpus"].pop("n_duplicates")

    schema_file = ProjectPaths.discover(None).optional(SCHEMA_FILE)
    assert schema_file is not None
    assert validate(data, load_schema(schema_file)) == []


# --- el camí de la interfície: textos repetits que hi arriben dues vegades ---------------------


def test_repeated_texts_from_the_interface_count_once() -> None:
    """Qui puja dues vegades el mateix fitxer no infla el corpus sense adonar-se'n."""
    from parafrasi_cat.style import corpus_from_texts

    corpus = corpus_from_texts([TEXT, OTHER, TEXT.replace("\n", "\r\n")])

    assert [d.name for d in corpus.documents] == ["text-1", "text-2"]
    assert [(e.name, e.duplicate_of) for e in corpus.duplicates] == [("text-3", "text-1")]


def test_the_interface_message_says_what_was_left_out() -> None:
    from parafrasi_cat.web.service import _fingerprint_message

    assert _fingerprint_message("autor", 3, 0) == "Empremta «autor» creada amb 3 textos."
    one = _fingerprint_message("autor", 2, 1)
    assert "1 text repetit" in one and "mateix contingut" in one
    assert "2 textos repetits" in _fingerprint_message("autor", 2, 2)
