"""Classificació epistemològica explícita i bloqueig dels canvis de certesa."""

from __future__ import annotations

import pytest

from parafrasi_cat.candidates import Candidate
from parafrasi_cat.core import SemanticRisk, Span, Transformation, TransformationType
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.validation import (
    EpistemicLexicon,
    EpistemicValidator,
    ValidationContext,
    ValidationDimension,
    rule_ids_of,
)
from parafrasi_cat.validation.epistemic import EPISTEMOLOGY_FILE

EXPRESSIONS = (
    "és",
    "sembla",
    "podria",
    "potser",
    "probablement",
    "és possible",
    "és probable",
    "permet plantejar",
    "indica",
    "suggereix",
    "demostra",
    "confirma",
    "no es pot demostrar",
)


@pytest.fixture(scope="module")
def lexicon(paths: ProjectPaths) -> EpistemicLexicon:
    return EpistemicLexicon.load(paths.language() / EPISTEMOLOGY_FILE)


def transformation(
    source: str, before: str, after: str, rule_id: str = "r", chained: str = ""
) -> Transformation:
    start = source.index(before)
    return Transformation(
        rule_id=rule_id,
        text_before=before,
        text_after=after,
        changed_span=Span(start, start + len(before)),
        transformation_type=TransformationType.LEXICAL,
        confidence=0.9,
        semantic_risk=SemanticRisk.LOW,
        explanation="prova",
        metadata={"chained_rules": chained} if chained else {},
    )


def rewrite(source: str, before: str, after: str, **kwargs: str) -> Candidate:
    return Candidate.from_transformations(
        0, source, [transformation(source, before, after, **kwargs)]
    )


def test_the_listed_expressions_are_all_distinct_classes(lexicon: EpistemicLexicon) -> None:
    classes = {}
    for expression in EXPRESSIONS:
        cls = lexicon.classify_marker(expression)
        assert cls is not None, expression
        classes[expression] = cls
    assert len({c.id for c in classes.values()}) == len(EXPRESSIONS)
    assert classes["no es pot demostrar"].strength == 0
    assert classes["potser"].strength == classes["podria"].strength == 1
    assert classes["permet plantejar"].strength == 1
    assert classes["sembla"].strength == classes["probablement"].strength == 2
    assert classes["indica"].strength == classes["suggereix"].strength == 2
    assert classes["indica"].id != classes["suggereix"].id
    assert classes["és"].strength == 3 and classes["és"].counted is False
    assert classes["demostra"].strength == classes["confirma"].strength == 4
    assert classes["demostra"].id != classes["confirma"].id
    assert lexicon.classify_marker("plou") is None
    assert lexicon.class_of("necessity").on_scale is False


def test_profiles_mask_longer_phrases_first(lexicon: EpistemicLexicon) -> None:
    profile = lexicon.profile("És possible que sembli evident, però no es pot demostrar.")
    assert [m.class_id for m in profile.matches] == ["possibility", "impossibility"]
    assert profile.counts == {"possibility": 1, "impossibility": 1}
    assert "possibilitat" in profile.describe()
    unmarked = lexicon.profile("La casa és de fusta.")
    assert unmarked.counts == {} and [m.class_id for m in unmarked.matches] == ["assertion"]


def test_change_directions(lexicon: EpistemicLexicon) -> None:
    up = lexicon.change("Sembla que plou.", "Plou.")
    assert up is not None and up.direction == "augmenta el grau de certesa"
    assert [m.class_id for m in up.lost] == ["appearance"] and up.gained == ()
    to_assertion = lexicon.change("Sembla que el motiu és antic.", "El motiu és antic.")
    assert to_assertion is not None
    assert [m.class_id for m in to_assertion.gained] == ["assertion"]
    assert "«és» (afirmació" in to_assertion.describe()
    certain = lexicon.change("Sembla que plou.", "És evident que plou.")
    assert certain is not None and certain.direction == "augmenta el grau de certesa"
    down = lexicon.change("Demostra que plou.", "Suggereix que plou.")
    assert down is not None and down.direction == "redueix el grau de certesa"
    hedge_added = lexicon.change("Plou.", "Potser plou.")
    assert hedge_added is not None and hedge_added.direction == "redueix el grau de certesa"
    function = lexicon.change("Indica que plou.", "Suggereix que plou.")
    assert function is not None and function.direction.startswith("canvia la funció")
    assert lexicon.change("Cal plegar.", "És necessari plegar.") is None
    assert lexicon.change("Potser plou.", "Plou, potser.") is None
    assert lexicon.change("Podria ploure.", "És possible que plogui.") is not None
    modality = lexicon.change("Cal plegar.", "Convé plegar.")
    assert modality is not None and "fora de l'escala" in modality.direction


def test_validator_blocks_hypothesis_to_certainty(lexicon: EpistemicLexicon) -> None:
    v = EpistemicValidator(lexicon)
    source = "Sembla que el motiu podria procedir del tractat."
    for before, after in (
        ("Sembla que el motiu podria", "El motiu podria"),
        ("Sembla que", "És evident que"),
        ("podria procedir", "procedeix"),
        ("Sembla que", "Es confirma que"),
    ):
        result = v.validate(rewrite(source, before, after), ValidationContext(source))
        assert not result.ok, (before, after)
        assert result.errors[0].dimension is ValidationDimension.EPISTEMIC
        assert "sense cap regla que ho autoritzi" in result.errors[0].message
    strong = "Aquesta dada demostra que el motiu és italià."
    for before, after in (
        ("demostra", "suggereix"),
        ("demostra", "confirma"),
        ("demostra", "indica"),
        ("demostra que", "potser demostra que"),
    ):
        assert not v.validate(rewrite(strong, before, after), ValidationContext(strong)).ok


def test_validator_accepts_neutral_rewrites(lexicon: EpistemicLexicon) -> None:
    v = EpistemicValidator(lexicon)
    source = "Potser el motiu procedeix del tractat, i cal revisar-ho."
    moved = Candidate(0, source, "Cal revisar-ho, i potser el motiu procedeix del tractat.")
    assert v.validate(moved, ValidationContext(source)).ok
    deontic = rewrite(source, "cal revisar-ho", "és necessari revisar-ho")
    assert v.validate(deontic, ValidationContext(source)).ok
    lexical = rewrite(source, "procedeix", "prové")
    assert v.validate(lexical, ValidationContext(source)).ok
    assert v.validate(Candidate.identity(0, source), ValidationContext(source)).ok


def test_explicit_rule_authorizes_the_change(lexicon: EpistemicLexicon) -> None:
    source = "Sembla que plou."
    candidate = rewrite(source, "Sembla que plou", "Plou", rule_id="epist.autoritzada")
    blocked = EpistemicValidator(lexicon).validate(candidate, ValidationContext(source))
    assert not blocked.ok
    allowed = EpistemicValidator(lexicon, ["epist.autoritzada"])
    result = allowed.validate(candidate, ValidationContext(source))
    assert result.ok
    assert result.warnings and "autoritzat" in result.warnings[0].message
    assert allowed.authorized_rules == frozenset({"epist.autoritzada"})
    # Una regla encadenada no autoritzada bloqueja el canvi.
    chained = rewrite(
        source, "Sembla que plou", "Plou", rule_id="epist.autoritzada", chained="lexical.x"
    )
    assert rule_ids_of(chained.transformations[0]) == ("epist.autoritzada", "lexical.x")
    assert not allowed.validate(chained, ValidationContext(source)).ok
    # El candidat sencer també es comprova quan cap transformació no explica el canvi.
    whole = Candidate(0, source, "Plou.")
    result = allowed.validate(whole, ValidationContext(source))
    assert not result.ok and "perfil epistemològic de la frase" in result.errors[0].message
