"""Subordre «parafrasi-cat style»."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from parafrasi_cat.cli import main


@pytest.fixture(scope="module")
def examples_dir(project_root: Path) -> Path:
    return project_root / "corpus" / "exemples"


@pytest.fixture(scope="module")
def built(examples_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    out_dir = tmp_path_factory.mktemp("empremtes")
    files: dict[str, Path] = {}
    for style in ("concis", "academic"):
        files[style] = out_dir / f"{style}.json"
        assert (
            main(["style", "build", str(examples_dir / style), "-o", str(files[style]), "-q"]) == 0
        )
    return files


def test_style_build_writes_fingerprint_and_profile(
    examples_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "narratiu.json"
    profile = tmp_path / "narratiu.yaml"
    code = main(
        [
            "style",
            "build",
            str(examples_dir / "narratiu"),
            "--validation",
            str(examples_dir / "narratiu-validacio"),
            "--exclude",
            "inexistent*",
            "-o",
            str(output),
            "--profile",
            str(profile),
            "-n",
            "prova-narrativa",
            "-d",
            "Corpus de prova",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Empremta «prova-narrativa»" in out and "validació: 2 documents" in out
    assert "prefereix «apareix»" in out
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["name"] == "prova-narrativa" and data["description"] == "Corpus de prova"
    assert data["validation"]["n_documents"] == 2
    assert output.read_text(encoding="utf-8").endswith("}\n")
    profile_data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert profile_data["fingerprint"] == str(output)
    assert profile_data["sentence_length"]["target_mean"] == pytest.approx(
        data["features"]["sentence_length"]["value"]
    )


def test_style_show(built: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["style", "show", str(built["concis"])]) == 0
    out = capsys.readouterr().out
    assert "Empremta «concis»" in out and "comes per 100 paraules" in out
    assert "prefereix «és»" in out


def test_style_compare_text_and_json(
    built: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["style", "compare", str(built["concis"]), str(built["academic"]), "--top", "3"]) == 0
    )
    out = capsys.readouterr().out
    assert "Comparació d'empremtes" in out and "clarament diferents" in out
    assert main(["style", "compare", str(built["concis"]), str(built["academic"]), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["a"] == "concis" and data["b"] == "academic"
    assert data["distance"] >= 0.4 and data["items"]


def test_style_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["style", "build", str(tmp_path / "no-existeix")]) == 1
    assert "error" in capsys.readouterr().err
    assert main(["style", "compare", str(tmp_path / "a.json"), str(tmp_path / "b.json")]) == 1
    assert "error" in capsys.readouterr().err
    empty = tmp_path / "buit"
    empty.mkdir()
    assert main(["style", "build", str(empty), "-o", str(tmp_path / "x.json")]) == 1
    assert "cap document" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["style"])


def test_plain_cli_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["Hola món."]) == 0
    assert capsys.readouterr().out == "Hola món.\n"
