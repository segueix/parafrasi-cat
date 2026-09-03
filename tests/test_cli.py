from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from parafrasi_cat.cli import main


def test_text_argument_is_returned_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["El 12 de gener de 2020 va ploure a Girona."]) == 0
    captured = capsys.readouterr()
    assert captured.out == "El 12 de gener de 2020 va ploure a Girona.\n"
    assert captured.err == ""


def test_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("Hola món.\n"))
    assert main([]) == 0
    assert capsys.readouterr().out == "Hola món.\n"


def test_explain_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--explain", "Hola món."]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Hola món.\n"
    assert "Informe" in captured.err


def test_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json", "--rules", "exemple-lexic", "Gairebé tothom."]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["output_text"] == "Quasi tothom."
    assert data["transformations"][0]["rule_id"] == "lexical.substitution"


def test_rules_and_protect_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rules", "exemple-lexic", "Gairebé tothom."]) == 0
    assert capsys.readouterr().out == "Quasi tothom.\n"
    assert main(["--rules", "exemple-lexic", "--protect", "gairebé", "Gairebé tothom."]) == 0
    assert capsys.readouterr().out == "Gairebé tothom.\n"
    assert main(["--rules", "exemple-lexic", "--min-confidence", "0.99", "Gairebé tothom."]) == 0
    assert capsys.readouterr().out == "Gairebé tothom.\n"


def test_input_and_output_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "entrada.txt"
    source.write_text("Sovint plou.\n", encoding="utf-8")
    target = tmp_path / "sortida.txt"
    assert main(["--input", str(source), "--output", str(target), "--rules", "exemple-lexic"]) == 0
    assert target.read_text(encoding="utf-8") == "Freqüentment plou.\n"
    assert capsys.readouterr().out == ""


def test_config_file(
    tmp_path: Path, project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"rule_set": "exemple-lexic", "protected_terms": ["sovint"]}), encoding="utf-8"
    )
    assert main(["--config", str(config), "Sovint plou gairebé sempre."]) == 0
    assert capsys.readouterr().out == "Sovint plou quasi sempre.\n"


def test_errors_are_reported(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--rules", "inexistent", "Hola."]) == 1
    assert "error" in capsys.readouterr().err
    assert main(["--home", "/directori/inexistent", "Hola."]) == 1
    assert "error" in capsys.readouterr().err


def test_info(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--info", "--rules", "exemple-lexic"]) == 0
    out = capsys.readouterr().out
    assert "rule_set: exemple-lexic" in out
    assert "lexical.substitution" in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "parafrasi-cat" in capsys.readouterr().out


def test_module_entry_point(project_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "parafrasi_cat", "Hola món."],
        capture_output=True,
        text=True,
        cwd=project_root,
        env={"PYTHONPATH": str(project_root / "src"), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "Hola món.\n"
