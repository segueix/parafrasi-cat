"""Fase 6: diccionaris editables per projecte (activació, protecció, formes preferides)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parafrasi_cat import PipelineConfig, build_pipeline
from parafrasi_cat.analyzer import RuleBasedAnalyzer
from parafrasi_cat.candidates import Candidate
from parafrasi_cat.cli import main
from parafrasi_cat.core import ConfigError
from parafrasi_cat.dictionaries import (
    DictionaryEntry,
    DictionarySet,
    FormStatus,
    TermDictionary,
    normalize_term,
)
from parafrasi_cat.resources import ProjectPaths
from parafrasi_cat.rules import RuleContext
from parafrasi_cat.rules.dictionary import DictionaryPreferenceRule
from parafrasi_cat.validation import ProtectedTermValidator, ValidationContext


def write_dictionary(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- càrrega ---------------------------------------------------------------------------------


def test_load_dictionary_fields(paths: ProjectPaths) -> None:
    historia = TermDictionary.load(paths.resolve_dictionary("historia"))
    assert historia.name == "historia" and historia.language == "ca" and historia.description
    assert historia.path == paths.dictionaries / "historia.yml"
    entry = historia.entry_for("sarcòfag")
    assert entry is not None
    assert entry.term == "sarcòfag"
    assert entry.preferred == ("sarcòfag",)
    assert entry.accepted == ("sarcòfag funerari",)
    assert entry.avoid == ("fèretre",)
    assert entry.protected is True
    assert entry.pos == "nom"
    assert entry.notes == "No substituir en contextos arqueològics."
    assert historia.status_of("fèretre") is FormStatus.AVOID
    assert historia.status_of("Sarcòfag funerari") is FormStatus.ACCEPTED
    assert historia.status_of("SARCÒFAG") is FormStatus.PREFERRED
    assert historia.status_of("inexistent") is None
    assert "sarcòfag" in historia.protected_terms
    assert "sarcòfag funerari" in historia.protected_terms
    assert historia.is_protected("Sarcòfag") and not historia.is_protected("crani")
    substitutions = {s.source: s.target for s in historia.substitutions}
    assert substitutions["fèretre"] == "sarcòfag" and substitutions["enterro"] == "enterrament"
    assert all(s.confidence == historia.confidence for s in historia.substitutions)
    assert entry.describe().startswith("«sarcòfag» (nom) preferida: sarcòfag")
    assert "[protegit]" in entry.describe()
    entries = historia.to_dict()["entries"]
    assert isinstance(entries, list) and entries[0]["protected"] is True
    assert "sarcòfag" in historia.summary()


def test_entry_defaults_and_validation() -> None:
    entry = DictionaryEntry("cavall")
    assert entry.preferred == ("cavall",) and entry.preferred_form == "cavall"
    assert entry.forms == ("cavall",) and entry.protected_forms == ()
    assert DictionaryEntry("Peó", protected=True).protected_forms == ("Peó",)
    assert DictionaryEntry("  dama ", accepted=("reina", "Reina")).accepted == ("reina",)
    assert DictionaryEntry("dama").status_of("Dama") is FormStatus.PREFERRED
    with pytest.raises(ConfigError):
        DictionaryEntry("  ")
    with pytest.raises(ConfigError):
        DictionaryEntry("tauler", preferred=("tauler",), avoid=("Tauler",))
    with pytest.raises(ConfigError):
        DictionaryEntry.from_mapping({"term": "x", "prefered": ["y"]})
    with pytest.raises(ConfigError):
        TermDictionary(
            "dos", (DictionaryEntry("alfil", avoid=("bisbe",)), DictionaryEntry("bisbe"))
        )
    with pytest.raises(ConfigError):
        TermDictionary("x", confidence=2.0)
    with pytest.raises(ConfigError):
        TermDictionary.from_mapping({"entrades": []}, name="x")
    assert normalize_term("  Escac  i ’Mat ") == "escac i 'mat"
    assert FormStatus.AVOID.weight == -1.0 and FormStatus.PREFERRED.label == "forma preferida"


def test_shipped_dictionaries_are_valid(paths: ProjectPaths) -> None:
    files = sorted(paths.dictionaries.glob("*.yml"))
    assert {f.stem for f in files} >= {"general", "historia", "medieval", "escacs", "noms_propis"}
    dictionaries = DictionarySet.load(files)
    assert len(dictionaries) == len(files)
    for dictionary in dictionaries.dictionaries:
        assert dictionary.description and dictionary.entries, dictionary.name
        for entry in dictionary.entries:
            assert entry.term and entry.preferred, (dictionary.name, entry.term)
    names = next(d for d in dictionaries.dictionaries if d.name == "noms_propis")
    assert all(entry.protected for entry in names.entries)
    assert dictionaries.conflicts() == ()
    assert "Oddo Altoviti" in dictionaries.protected_terms


# --- activació simultània --------------------------------------------------------------------


def test_several_dictionaries_active_at_once(paths: ProjectPaths) -> None:
    both = DictionarySet.load(
        [paths.resolve_dictionary("historia"), paths.resolve_dictionary("escacs")]
    )
    assert both.names == ("historia", "escacs") and bool(both) and len(both) == 2
    found = both.lookup("bisbe")
    assert found is not None
    assert found.dictionary.name == "escacs" and found.status is FormStatus.AVOID
    assert found.entry.term == "alfil"
    feretre = both.lookup("Fèretre")
    assert feretre is not None and feretre.dictionary.name == "historia"
    assert both.status_of("cap") is None
    sources = [s.source for s in both.substitutions]
    assert "fèretre" in sources and "bisbe" in sources
    assert set(both.protected_terms) >= {"sarcòfag", "escac i mat"}
    assert not DictionarySet() and DictionarySet().summary() == "Cap diccionari actiu"
    assert "Diccionaris actius: historia, escacs" in both.summary()


def test_first_dictionary_wins_and_conflicts_are_listed() -> None:
    first = TermDictionary("primer", (DictionaryEntry("tanmateix", accepted=("però",)),))
    second = TermDictionary("segon", (DictionaryEntry("tanmateix", avoid=("però",)),))
    ordered = DictionarySet((first, second))
    assert ordered.status_of("però") is FormStatus.ACCEPTED
    assert ordered.substitutions == ()
    reversed_order = DictionarySet((second, first))
    assert reversed_order.status_of("però") is FormStatus.AVOID
    assert [(s.source, s.target) for s in reversed_order.substitutions] == [("però", "tanmateix")]
    conflicts = ordered.conflicts()
    assert len(conflicts) == 1 and conflicts[0].form == "però"
    assert conflicts[0].statuses == (("primer", FormStatus.ACCEPTED), ("segon", FormStatus.AVOID))
    assert "mana «primer»" in conflicts[0].describe()
    assert "Conflictes" in ordered.summary()
    with pytest.raises(ConfigError):
        DictionarySet((first, first))


def test_protection_is_cumulative_and_blocks_substitutions() -> None:
    protecting = TermDictionary("noms", (DictionaryEntry("fèretre", protected=True),))
    avoiding = TermDictionary("historia", (DictionaryEntry("sarcòfag", avoid=("fèretre",)),))
    for order in ((protecting, avoiding), (avoiding, protecting)):
        dictionaries = DictionarySet(order)
        assert dictionaries.is_protected("Fèretre")
        assert dictionaries.protecting("fèretre") is protecting
        assert dictionaries.substitutions == ()
        assert "fèretre" in dictionaries.protected_terms


# --- regla de formes preferides ----------------------------------------------------------------


def test_dictionary_rule_replaces_avoided_forms(catalan_analyzer: RuleBasedAnalyzer) -> None:
    pipeline = build_pipeline(PipelineConfig(dictionaries=("historia",)))
    assert pipeline.dictionary_names == ("historia",)
    assert "dictionary.preferred_form" in pipeline.rule_set.rule_ids
    result = pipeline.run("Van trobar un fèretre de pedra i un altre fèretre.")
    assert result.output_text == "Van trobar un sarcòfag de pedra i un altre sarcòfag."
    assert result.dictionary_names == ("historia",)
    transformation = result.transformations[0]
    assert transformation.rule_id == DictionaryPreferenceRule.DEFAULT_ID
    assert "diccionari «historia»" in transformation.explanation
    assert "No substituir en contextos arqueològics" in transformation.explanation
    assert transformation.metadata["dictionary"] == "historia"
    assert transformation.metadata["term"] == "sarcòfag"
    assert transformation.metadata["category"] == "diccionari"
    selected = result.sentences[0].selected
    assert selected.score is not None and selected.score.components["preferencies"] > 0
    assert "elimina «fèretre»" in selected.score.preference_explanation
    assert "Diccionaris actius: historia" in result.report()
    # Sense formes a evitar al text, no hi ha cap proposta.
    assert pipeline.run("Van trobar un sarcòfag.").sentences[0].alternatives == ()
    # Les majúscules es conserven (sense fragments protegits al context).
    rule = next(r for r in pipeline.rule_set.rules if isinstance(r, DictionaryPreferenceRule))
    sentence = catalan_analyzer.analyze("Fèretre de pedra.").sentences[0]
    proposals = list(rule.propose(RuleContext(sentence=sentence)))
    assert [t.text_after for t in proposals] == ["Sarcòfag"]


def test_dictionary_protected_term_blocks_stylistic_rules(tmp_path: Path) -> None:
    dictionary = write_dictionary(
        tmp_path / "prova.yml",
        "description: prova\nentries:\n  - term: gairebé\n    protected: true\n",
    )
    config = PipelineConfig(rule_set="exemple-lexic", dictionaries=(str(dictionary),))
    result = build_pipeline(config).run("Gairebé tothom ho sap.")
    assert result.output_text == "Gairebé tothom ho sap."
    assert result.sentences[0].alternatives == ()
    protected = [p for p in result.protected_spans if p.detector_id == "user_term.dictionary"]
    assert [p.text for p in protected] == ["Gairebé"]
    assert result.dictionary_names == ("prova",)
    # Sense el diccionari, la mateixa regla sí que s'aplica.
    plain = build_pipeline(PipelineConfig(rule_set="exemple-lexic"))
    assert plain.run("Gairebé tothom ho sap.").output_text == "Quasi tothom ho sap."


def test_protected_term_validator_covers_dictionary_terms() -> None:
    dictionaries = DictionarySet(
        (TermDictionary("h", (DictionaryEntry("sarcòfag", protected=True),)),)
    )
    validator = ProtectedTermValidator(dictionaries.protected_terms)
    source = "El sarcòfag és de marbre."
    moved = validator.validate(
        Candidate(0, source, "De marbre és el sarcòfag."), ValidationContext(source)
    )
    assert moved.ok
    altered = validator.validate(
        Candidate(0, source, "El fèretre és de marbre."), ValidationContext(source)
    )
    assert not altered.ok and "sarcòfag" in altered.errors[0].message


def test_explicit_protection_beats_dictionary_avoid() -> None:
    config = PipelineConfig(dictionaries=("historia",), protected_terms=("fèretre",))
    result = build_pipeline(config).run("Van trobar un fèretre de pedra.")
    assert result.output_text == "Van trobar un fèretre de pedra."
    assert result.sentences[0].alternatives == ()
    assert any(
        p.detector_id == "user_term.list" and p.text == "fèretre" for p in result.protected_spans
    )


def test_dictionary_protection_beats_avoid_of_another_dictionary(tmp_path: Path) -> None:
    protecting = write_dictionary(
        tmp_path / "noms.yml",
        "description: noms\nentries:\n  - term: fèretre\n    protected: true\n",
    )
    for order in (("historia", str(protecting)), (str(protecting), "historia")):
        result = build_pipeline(PipelineConfig(dictionaries=order)).run("Un fèretre de pedra.")
        assert result.output_text == "Un fèretre de pedra."
        assert (
            "dictionary.preferred_form" not in result.rule_ids
            or result.sentences[0].alternatives == ()
        )


def test_cli_dictionary_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dictionary", "historia", "--json", "Van trobar un fèretre de pedra."]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["output_text"] == "Van trobar un sarcòfag de pedra."
    assert data["dictionaries"] == ["historia"]
    assert main(["--dictionary", "historia", "--dictionary", "escacs", "--info"]) == 0
    out = capsys.readouterr().out
    assert "dictionaries: ['historia', 'escacs']" in out and "dictionary.preferred_form" in out
    assert main(["--dictionary", "inexistent", "Hola."]) == 1
    assert "diccionari" in capsys.readouterr().err
