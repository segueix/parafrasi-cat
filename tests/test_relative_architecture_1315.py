"""v1.3.15: relatives passives explicatives ↔ participials guiades pel parser.

Les proves miren propietats i no una sortida global fixa: la transformació només
pot aparèixer quan l'arbre identifica l'antecedent, la construcció és
explicativa i no hi ha negació ni contradicció de concordança.
"""

from __future__ import annotations

from parafrasi_cat.analyzer.sentences import Sentence
from parafrasi_cat.core import Span, TransformationType
from parafrasi_cat.rules.base import RuleContext
from parafrasi_cat.rules.definition import RuleDefinition
from parafrasi_cat.rules.registry import default_registry
from parafrasi_cat.rules.relative import RelativeArchitectureRule
from parafrasi_cat.syntax.analysis import SentenceSyntax, SyntaxToken


def _token(
    text: str,
    surface: str,
    index: int,
    *,
    dep: str,
    head: int,
    pos: str,
    occurrence: int = 0,
    lemma: str | None = None,
    number: str | None = None,
    gender: str | None = None,
    mood: str | None = None,
    verb_form: str | None = None,
    pron_type: str | None = None,
    adv_type: str | None = None,
) -> SyntaxToken:
    start = -1
    cursor = 0
    for _ in range(occurrence + 1):
        start = text.index(surface, cursor)
        cursor = start + len(surface)
    return SyntaxToken(
        index=index,
        text=surface,
        lemma=lemma or surface.casefold(),
        pos=pos,
        dep=dep,
        head=head,
        start=start,
        end=start + len(surface),
        number=number,
        gender=gender,
        mood=mood,
        verb_form=verb_form,
        pron_type=pron_type,
        adv_type=adv_type,
    )


def _relative_analysis(text: str, *, negated: bool = False) -> SentenceSyntax:
    # Índexs en ordre textual: monument(0), que(1), [no(2)], fou, participi, data, és.
    shift = 1 if negated else 0
    participle_i = 3 + shift
    root_i = 5 + shift
    tokens = [
        _token(
            text,
            "monument",
            0,
            dep="nsubj",
            head=root_i,
            pos="NOUN",
            number="sg",
            gender="m",
        ),
        _token(
            text,
            "que",
            1,
            dep="nsubj:pass",
            head=participle_i,
            pos="PRON",
            pron_type="Rel",
        ),
    ]
    if negated:
        tokens.append(
            _token(text, "no", 2, dep="advmod", head=participle_i, pos="ADV", lemma="no")
        )
    tokens.extend(
        [
            _token(
                text,
                "fou",
                2 + shift,
                dep="aux:pass",
                head=participle_i,
                pos="AUX",
                mood="ind",
                verb_form="Fin",
            ),
            _token(
                text,
                "encarregat",
                participle_i,
                dep="acl:relcl",
                head=0,
                pos="VERB",
                number="sg",
                gender="m",
                verb_form="Part",
            ),
            _token(
                text,
                "1507",
                4 + shift,
                dep="obl:tmod",
                head=participle_i,
                pos="NUM",
                adv_type="Tim",
            ),
            _token(
                text,
                "és",
                root_i,
                dep="ROOT",
                head=root_i,
                pos="AUX",
                mood="ind",
                verb_form="Fin",
            ),
        ]
    )
    return SentenceSyntax(text, tuple(tokens), source="test")


def _participial_analysis(text: str, *, number: str | None = "sg") -> SentenceSyntax:
    tokens = (
        _token(
            text,
            "monument",
            0,
            dep="nsubj",
            head=3,
            pos="NOUN",
            number=number,
            gender="m",
        ),
        _token(
            text,
            "encarregat",
            1,
            dep="acl",
            head=0,
            pos="VERB",
            number=number,
            gender="m",
            verb_form="Part",
        ),
        _token(text, "1507", 2, dep="obl:tmod", head=1, pos="NUM", adv_type="Tim"),
        _token(
            text,
            "és",
            3,
            dep="ROOT",
            head=3,
            pos="AUX",
            mood="ind",
            verb_form="Fin",
        ),
    )
    return SentenceSyntax(text, tokens, source="test")


def _ctx(text: str, analysis: SentenceSyntax) -> RuleContext:
    sentence = Sentence(0, text, Span(0, len(text)), ())
    return RuleContext(sentence=sentence, document_text=text, analysis=analysis)


def _rule() -> RelativeArchitectureRule:
    return RelativeArchitectureRule(
        RuleDefinition(
            rule_id="subordinada.relativa_participial_parser",
            engine="relative_architecture",
            category="subordinada",
            level=3,
            transformation_type=TransformationType.SYNTACTIC,
            confidence=0.78,
            description="Relativa passiva explicativa ↔ participial",
        )
    )


def test_explanatory_passive_relative_offers_two_structural_architectures() -> None:
    text = "El monument, que fou encarregat el 1507, és a Florència."
    proposals = tuple(_rule().propose(_ctx(text, _relative_analysis(text))))
    outputs = [proposal.apply(text) for proposal in proposals]

    assert "El monument, encarregat el 1507, és a Florència." in outputs
    assert "Encarregat el 1507, el monument és a Florència." in outputs
    assert all("1507" in output for output in outputs)

    by_architecture = {proposal.metadata.get("architecture"): proposal for proposal in proposals}
    assert by_architecture["relative_to_participial"].metadata["family"] == "SUBORDINATION"
    assert by_architecture["relative_to_fronted_participial"].metadata["family"] == "REORDER"


def test_explanatory_participial_can_expand_when_event_is_anchored() -> None:
    text = "El monument, encarregat el 1507, és a Florència."
    proposals = tuple(_rule().propose(_ctx(text, _participial_analysis(text))))
    outputs = [proposal.apply(text) for proposal in proposals]
    assert "El monument, que fou encarregat el 1507, és a Florència." in outputs


def test_restrictive_relative_is_not_reduced() -> None:
    text = "El monument que fou encarregat el 1507 és a Florència."
    proposals = tuple(_rule().propose(_ctx(text, _relative_analysis(text))))
    assert not proposals


def test_negated_relative_is_not_reduced() -> None:
    text = "El monument, que no fou encarregat el 1507, és a Florència."
    proposals = tuple(_rule().propose(_ctx(text, _relative_analysis(text, negated=True))))
    assert not proposals


def test_participial_is_not_expanded_without_known_antecedent_number() -> None:
    text = "El monument, encarregat el 1507, és a Florència."
    proposals = tuple(_rule().propose(_ctx(text, _participial_analysis(text, number=None))))
    assert not proposals


def test_registry_exposes_relative_architecture_engine() -> None:
    assert "relative_architecture" in default_registry().available()
