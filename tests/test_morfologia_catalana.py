"""Fase 8A: morfologia catalana importada de Softcatalà.

Els tests que necessiten el recurs se salten si no s'ha importat, perquè el
recurs no es versiona (les dades són copyleft). Els que comproven la
importació i el comportament sense recurs s'executen sempre.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from parafrasi_cat.morphology import MorphFeatures, create_morphology_provider
from parafrasi_cat.morphology.catalan import RESOURCE_RELATIVE, CatalanMorphology
from parafrasi_cat.morphology.internal import InternalMorphology
from parafrasi_cat.morphology.provider import ChainedMorphology, NullMorphology, inflect_like
from parafrasi_cat.resources import ProjectPaths

IMPORTER = "scripts/import_softcatala.py"

#: Línies del format original de Softcatalà: «forma lema ETIQUETA».
SAMPLE = """\
presenta presentar VMIP3S00
presenten presentar VMIP3P00
apareix aparèixer VMIP3S00
apareixen aparèixer VMIP3P00
constitueix constituir VMIP3S00
constitueixen constituir VMIP3P00
constituïx constituir VMIP3S0V
constituïxen constituir VMIP3P0V
és ser VSIP3S00
són ser VSIP3P00
fet fer VMP00SM0
feta fer VMP00SF0
fets fer VMP00PM0
fetes fer VMP00PF0
realitzat realitzar VMP00SM0
realitzada realitzar VMP00SF0
realitzats realitzar VMP00PM0
realitzades realitzar VMP00PF0
sarcòfag sarcòfag NCMS000
sarcòfags sarcòfag NCMP000
crani crani NCMS000
cranis crani NCMP000
antic antic AQ0MS0
antiga antic AQ0FS0
antics antic AQ0MP0
antigues antic AQ0FP0
féu fer VMIS3S00
Barcelona Barcelona NP00000
ràpidament ràpidament RG
"""


@pytest.fixture(scope="module")
def imported(tmp_path_factory: pytest.TempPathFactory, project_root: Path) -> CatalanMorphology:
    """Executa l'importador de veritat sobre una mostra petita del format original."""
    workspace = tmp_path_factory.mktemp("softcatala")
    source = workspace / "diccionari.txt"
    source.write_text(SAMPLE, encoding="utf-8")
    output = workspace / "catala.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / IMPORTER),
            "--input",
            str(source),
            "--output",
            str(output),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    return CatalanMorphology(output)


@pytest.fixture(scope="module")
def full(paths: ProjectPaths) -> CatalanMorphology:
    resource = CatalanMorphology.discover(paths.language())
    if resource is None:
        pytest.skip(
            "El recurs de Softcatalà no s'ha importat. "
            f"Executeu: python {IMPORTER} --source /ruta/a/catalan-dict-tools"
        )
    return resource


# --- importació reproduïble -----------------------------------------------------------------


def test_importer_records_provenance_and_licence(imported: CatalanMorphology) -> None:
    metadata = imported.metadata
    assert metadata["source_repository"] == "https://github.com/Softcatala/catalan-dict-tools"
    assert metadata["license"] == "GPL-2.0-or-later OR LGPL-2.1-or-later"
    assert "Jaume Ortolà" in metadata["attribution"]
    assert metadata["imported_at"] and metadata["resource_version"]
    assert int(metadata["n_entries"]) > 0
    sidecar = imported.path.with_suffix(".metadata.json")
    assert json.loads(sidecar.read_text(encoding="utf-8"))["license"] == metadata["license"]


def test_importer_keeps_only_what_the_engine_needs(imported: CatalanMorphology) -> None:
    # Els noms propis queden fora: el motor els protegeix i no els flexiona mai.
    assert imported.analyze("Barcelona") == ()
    assert imported.analyze("sarcòfag")  # els noms comuns sí que hi són
    assert imported.analyze("ràpidament")  # i els adverbis
    assert int(imported.metadata["n_noun"]) == 4


# --- anàlisi i generació --------------------------------------------------------------------


def test_lemma_and_features(imported: CatalanMorphology) -> None:
    assert imported.lemma("presenten") == "presentar"
    features = imported.features("presenten")
    assert features is not None
    assert features.to_dict() == {
        "pos": "verb",
        "number": "pl",
        "person": "3",
        "tense": "pres",
        "mood": "ind",
    }
    assert imported.lemma("sarcòfags") == "sarcòfag"
    noun = imported.features("sarcòfags", pos="noun")
    assert noun is not None and noun.number == "pl"
    assert imported.lemma("antigues", pos="adj") == "antic"
    # Verb irregular: el recurs en sap el lema, cosa que cap heurística de sufixos no faria.
    assert imported.lemma("féu") == "fer"
    irregular = imported.features("féu")
    assert irregular is not None and irregular.tense == "past"


def test_generate_never_invents_forms(imported: CatalanMorphology) -> None:
    singular = MorphFeatures(pos="verb", mood="ind", tense="pres", person="3", number="sg")
    assert imported.generate("presentar", singular) == ("presenta",)
    plural = MorphFeatures(pos="verb", mood="ind", tense="pres", person="3", number="pl")
    assert imported.generate("presentar", plural) == ("presenten",)
    assert imported.generate("sarcòfag", MorphFeatures(pos="noun", number="pl")) == ("sarcòfags",)
    assert imported.generate("antic", MorphFeatures(pos="adj", gender="f", number="pl")) == (
        "antigues",
    )
    # Lema desconegut o trets impossibles: res, mai una forma inventada.
    assert imported.generate("inexistentar", singular) == ()
    assert imported.generate("sarcòfag", MorphFeatures(pos="verb")) == ()
    assert imported.analyze("qwertyuiop") == ()
    assert imported.lemma("qwertyuiop") is None
    assert imported.features("qwertyuiop") is None
    assert imported.knows("sarcòfag") and not imported.knows("qwertyuiop")


def test_standard_forms_win_over_regional_variants(imported: CatalanMorphology) -> None:
    """El diccionari porta «constituïx» (valencià) i «constitueix»: mana l'estàndard."""
    assert imported.inflect_like("és", "constituir") == "constitueix"
    assert imported.inflect_like("són", "constituir") == "constitueixen"
    forms = imported.generate(
        "constituir", MorphFeatures(pos="verb", mood="ind", tense="pres", person="3", number="sg")
    )
    assert forms[0] == "constitueix" and "constituïx" in forms


@pytest.mark.parametrize(
    ("form", "lemma", "expected"),
    [
        ("presenta", "aparèixer", "apareix"),
        ("presenten", "aparèixer", "apareixen"),
        ("apareix", "presentar", "presenta"),
        ("apareixen", "presentar", "presenten"),
        ("és", "constituir", "constitueix"),
        ("són", "constituir", "constitueixen"),
        ("constitueix", "ser", "és"),
        ("constitueixen", "ser", "són"),
        ("fet", "realitzar", "realitzat"),
        ("feta", "realitzar", "realitzada"),
        ("fets", "realitzar", "realitzats"),
        ("fetes", "realitzar", "realitzades"),
        ("realitzada", "fer", "feta"),
        ("realitzades", "fer", "fetes"),
    ],
)
def test_inflect_like_replaces_the_manual_mappings(
    imported: CatalanMorphology, form: str, lemma: str, expected: str
) -> None:
    """Cada parella que abans era un mapatge escrit a mà surt ara de la morfologia."""
    assert imported.inflect_like(form, lemma) == expected


def test_agreement_check(imported: CatalanMorphology) -> None:
    assert imported.agrees("sarcòfag", "antic") is True
    assert imported.agrees("sarcòfags", "antic") is False
    assert imported.agrees("sarcòfag", "qwertyuiop") is None


# --- encadenament i reserva -----------------------------------------------------------------


def test_chained_provider_prefers_the_first_that_knows(imported: CatalanMorphology) -> None:
    chained = ChainedMorphology(NullMorphology(), imported)
    assert inflect_like(chained, "és", "constituir") == "constitueix"
    assert ChainedMorphology().analyze("és") == ()
    assert ChainedMorphology(NullMorphology()).generate("ser", MorphFeatures()) == ()


def test_without_the_resource_the_engine_falls_back(paths: ProjectPaths, tmp_path: Path) -> None:
    """Sense recurs importat, la fàbrica retorna l'analitzador intern de sempre."""
    assert CatalanMorphology.discover(tmp_path) is None
    provider = create_morphology_provider("catalan", paths.language())
    if CatalanMorphology.discover(paths.language()) is None:
        assert isinstance(provider, InternalMorphology)
    else:
        assert isinstance(provider, ChainedMorphology)
        assert isinstance(provider.providers[0], CatalanMorphology)
        assert isinstance(provider.providers[1], InternalMorphology)
    # El fallback no inventa res tampoc.
    assert inflect_like(NullMorphology(), "és", "constituir") is None


def test_missing_resource_is_reported_clearly(tmp_path: Path) -> None:
    from parafrasi_cat.core import ResourceError

    with pytest.raises(ResourceError):
        CatalanMorphology(tmp_path / "no-existeix.sqlite")
    broken = tmp_path / "trencat.sqlite"
    broken.write_text("això no és una base de dades", encoding="utf-8")
    with pytest.raises(ResourceError):
        CatalanMorphology(broken)
    assert CatalanMorphology.discover(tmp_path) is None


# --- recurs complet (només si l'usuari l'ha importat) ----------------------------------------


def test_full_resource_covers_the_altoviti_vocabulary(full: CatalanMorphology) -> None:
    assert len(full) > 500_000
    assert full.path.name == Path(RESOURCE_RELATIVE).name
    for form, lemma in [
        ("sarcòfag", "sarcòfag"),
        ("cranis", "crani"),
        ("serps", "serp"),
        ("creuades", "creuar"),
        ("encarregat", "encarregar"),
        ("finalitzat", "finalitzar"),
    ]:
        assert full.lemma(form) == lemma, form
    assert full.inflect_like("és", "constituir") == "constitueix"
    assert full.inflect_like("finalitzat", "acabar") == "acabat"
