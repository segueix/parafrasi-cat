"""Moviment de blocs: reflexius lligats i coordinacions que no es poden partir.

Dos canvis, tots dos amb evidència de l'arbre i comprovats amb el parser real:

1. Un pronom que l'analitzador marca com a **reflexiu** (``Reflex=Yes``) i que
   té el verb dins del bloc no assenyala cap antecedent de fora: viatja amb el
   verb. Abans bloquejava el moviment igual que un pronom acusatiu.
2. Un bloc que deixaria una **conjunció coordinant despenjada** no es mou. El
   canvi anterior el va destapar: en «Quan apareix o quan es consolida, …» el
   motor movia només el primer membre i deixava «O quan es consolida, …».

Els tests amb l'arbre construït a mà comproven la lògica de
:meth:`SentenceSyntax.block_check`; els que fan servir el parser real
s'ometen si no hi ha cap model instal·lat, i s'hi diu.
"""

from __future__ import annotations

import pytest

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import apply_mode
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken
from parafrasi_cat.syntax.spacy_parser import SpacySyntax

REFLEXIVE = "La reina, quan apareix o quan es consolida, tampoc no necessita cap explicació."
ACCUSATIVE = (
    "El cavaller és reconeixible perquè el cavall, l'armament i la funció militar "
    "el fan transparent."
)


# --- arbres simulats: la lògica, sense dependre de cap model ----------------------------------


def _token(index: int, text: str, pos: str, dep: str, head: int, start: int, **extra: object):  # type: ignore[no-untyped-def]
    return SyntaxToken(
        index=index,
        text=text,
        lemma=text.lower(),
        pos=pos,
        dep=dep,
        head=head,
        start=start,
        end=start + len(text),
        **extra,  # type: ignore[arg-type]
    )


def _clause_with(pronoun_dep: str, reflexive: bool | None) -> tuple[SentenceSyntax, int, int]:
    """«Quan es consolida, la reina calla.»: bloc «quan es consolida» (0-18)."""
    text = "Quan es consolida, la reina calla."
    tokens = (
        _token(0, "Quan", "SCONJ", "mark", 2, 0),
        _token(1, "es", "PRON", pronoun_dep, 2, 5, reflexive=reflexive, pron_type="Prs"),
        _token(2, "consolida", "VERB", "advcl", 6, 8, mood="ind"),
        _token(3, ",", "PUNCT", "punct", 6, 17),
        _token(4, "la", "DET", "det", 5, 19),
        _token(5, "reina", "NOUN", "nsubj", 6, 22),
        _token(6, "calla", "VERB", "ROOT", 6, 28, mood="ind"),
        _token(7, ".", "PUNCT", "punct", 6, 33),
    )
    return SentenceSyntax(text, tokens, source="prova"), 0, 17


def test_a_bound_reflexive_does_not_block_the_move() -> None:
    syntax, start, end = _clause_with("obj", True)
    assert syntax.bound_reflexives(start, end) == frozenset({1})
    check = syntax.block_check(start, end, to_front=True, clitic_spans=[_Span(5, 7)])
    assert check.ok, check.reasons


def test_a_pronoun_without_the_reflexive_feature_still_blocks() -> None:
    """Sense el tret, no s'endevina: el bloqueig es manté."""
    syntax, start, end = _clause_with("obj", None)
    assert syntax.bound_reflexives(start, end) == frozenset()
    check = syntax.block_check(start, end, to_front=True, clitic_spans=[_Span(5, 7)])
    assert not check.ok
    assert any("pronom" in reason for reason in check.reasons)


def test_an_unreliable_analysis_never_frees_a_reflexive() -> None:
    syntax, start, end = _clause_with("obj", True)
    doubtful = SentenceSyntax(syntax.text, syntax.tokens, _unconfident(), "prova")
    assert doubtful.bound_reflexives(start, end) == frozenset()


class _Span:
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end


def _unconfident():  # type: ignore[no-untyped-def]
    from parafrasi_cat.syntax.analysis import SyntaxConfidence

    return SyntaxConfidence(False, ("prova",))


def test_a_block_that_strands_a_conjunction_is_refused() -> None:
    """«Quan apareix o quan es consolida»: el primer membre no es mou tot sol."""
    text = "Quan apareix o quan es consolida, la reina calla."
    tokens = (
        _token(0, "Quan", "SCONJ", "mark", 1, 0),
        _token(1, "apareix", "VERB", "advcl", 7, 5, mood="ind"),
        _token(2, "o", "CCONJ", "cc", 5, 13),
        _token(3, "quan", "SCONJ", "mark", 5, 15),
        _token(4, "es", "PRON", "obj", 5, 20, reflexive=True, pron_type="Prs"),
        _token(5, "consolida", "VERB", "advcl", 7, 23, mood="ind"),
        _token(6, ",", "PUNCT", "punct", 7, 32),
        _token(7, "calla", "VERB", "ROOT", 7, 34, mood="ind"),
        _token(8, ".", "PUNCT", "punct", 7, 39),
    )
    syntax = SentenceSyntax(text, tokens, source="prova")
    left = syntax.block_check(0, 12, to_front=True)
    assert not left.ok
    assert any("coordinació" in reason for reason in left.reasons)
    # I un bloc que comencés per la conjunció, tampoc.
    assert not syntax.block_check(13, 32, to_front=True).ok


# --- amb el parser real -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def parser() -> SpacySyntax:
    found = SpacySyntax()
    if not found.available:
        pytest.skip("cal el parser local (scripts/install_parser.py)")
    return found


def test_the_parser_marks_the_reflexive_and_not_the_accusative(parser: SpacySyntax) -> None:
    """La distinció ve del model, no de cap llista de formes."""
    reflexive = parser.parse(REFLEXIVE)
    assert reflexive.confident
    assert any(t.text == "es" and t.reflexive is True for t in reflexive.tokens)

    accusative = parser.parse(ACCUSATIVE)
    assert accusative.confident
    pronouns = [t for t in accusative.tokens if t.pos == "PRON" and t.text == "el"]
    assert pronouns and all(t.reflexive is not True for t in pronouns)


@pytest.fixture(scope="module")
def deep_level3():  # type: ignore[no-untyped-def]
    pipeline = build_pipeline(apply_mode(PipelineConfig(rule_set="parafrasi"), "profund", 3))
    if not pipeline.syntax.available:
        pytest.skip("cal el parser local (scripts/install_parser.py)")
    return pipeline


def test_the_interposed_coordinated_clause_moves_whole(deep_level3) -> None:  # type: ignore[no-untyped-def]
    result = deep_level3.run(
        "La reina, quan apareix o quan es consolida, tampoc no necessita una explicació "
        "excessiva: ocupa el lloc immediat del poder."
    )
    texts = [c.candidate.text for s in result.sentences for c in s.candidates]
    assert any(t.startswith("Quan apareix o quan es consolida, la reina") for t in texts)
    # I cap candidat no parteix la coordinació.
    assert not any(t.startswith("O quan") or " o quan apareix" in t for t in texts)


def test_the_same_shape_with_other_words(deep_level3) -> None:  # type: ignore[no-untyped-def]
    """Mateixa estructura, vocabulari diferent: no hi ha cap excepció programada."""
    result = deep_level3.run(
        "El notari, quan actua o quan es pronuncia, tampoc no necessita cap justificació."
    )
    texts = [c.candidate.text for s in result.sentences for c in s.candidates]
    assert any(t.startswith("Quan actua o quan es pronuncia, el notari") for t in texts)


def test_the_accusative_pronoun_still_blocks_the_move(deep_level3) -> None:  # type: ignore[no-untyped-def]
    """Cas E: l'antecedent de «el» és fora del bloc i no es pot garantir."""
    result = deep_level3.run(ACCUSATIVE)
    sentence = result.sentences[0]
    moved = [
        c.candidate.text
        for c in sentence.candidates
        if c.candidate.text.startswith("Perquè el cavall")
    ]
    assert not moved
    assert any("perdria el referent" in note for note in sentence.notes)
