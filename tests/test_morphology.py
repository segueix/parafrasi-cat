from __future__ import annotations

from parafrasi_cat.morphology import (
    DictionaryMorphology,
    LexicalEntry,
    MorphFeatures,
    MorphologyProvider,
    NullMorphology,
)
from parafrasi_cat.resources import ProjectPaths


def test_null_morphology() -> None:
    provider: MorphologyProvider = NullMorphology()
    assert provider.analyze("cases") == ()
    assert provider.generate("casa", MorphFeatures(number="pl")) == ()


def test_dictionary_morphology() -> None:
    provider = DictionaryMorphology(
        [
            LexicalEntry("casa", "casa", MorphFeatures(pos="noun", gender="f", number="sg")),
            LexicalEntry("cases", "casa", MorphFeatures(pos="noun", gender="f", number="pl")),
        ]
    )
    assert len(provider) == 2
    assert provider.analyze("Cases")[0].lemma == "casa"
    assert provider.analyze("gos") == ()
    assert provider.generate("casa", MorphFeatures(number="pl")) == ("cases",)
    assert provider.generate("casa", MorphFeatures()) == ("casa", "cases")
    assert provider.generate("casa", MorphFeatures(gender="m")) == ()


def test_features() -> None:
    features = MorphFeatures.from_mapping({"pos": "verb", "person": 3, "number": "sg"})
    assert features.to_dict() == {"pos": "verb", "number": "sg", "person": "3"}
    assert features.matches(MorphFeatures(pos="verb"))
    assert not features.matches(MorphFeatures(pos="noun"))
    assert LexicalEntry("és", "ser", features).to_dict()["lemma"] == "ser"


def test_dictionary_from_file(paths: ProjectPaths) -> None:
    provider = DictionaryMorphology.from_file(paths.language() / "morphology" / "formes.yaml")
    assert len(provider) > 0
    assert provider.analyze("cases")[0].features.number == "pl"
    assert "són" in provider.generate("ser", MorphFeatures(number="pl", tense="pres"))
