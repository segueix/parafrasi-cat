from __future__ import annotations

from pathlib import Path

import pytest

from parafrasi_cat.core import ResourceError
from parafrasi_cat.resources import (
    ENV_HOME,
    ProjectPaths,
    as_bool,
    as_float,
    as_int,
    as_mapping,
    as_mapping_list,
    as_str,
    as_str_list,
    load_data,
    load_mapping,
    read_term_list,
)


def test_all_yaml_resources_load(project_root: Path) -> None:
    files = [*project_root.glob("resources/**/*.yaml"), *project_root.glob("rules/*.yaml")]
    assert files
    for file in files:
        data = load_mapping(file)
        assert isinstance(data, dict), file
        assert "description" in data, file


def test_discover_project_root(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_HOME, raising=False)
    assert ProjectPaths.discover().root == project_root
    assert ProjectPaths.discover(project_root).root == project_root
    monkeypatch.setenv(ENV_HOME, str(project_root))
    assert ProjectPaths.discover().root == project_root
    with pytest.raises(ResourceError):
        ProjectPaths.discover("/directori/inexistent")


def test_resolve_named_resources(paths: ProjectPaths) -> None:
    assert paths.resolve_rule_set("default") == paths.rules / "default.yaml"
    assert paths.resolve_rule_set("rules/default.yaml") == paths.rules / "default.yaml"
    assert paths.resolve_rule_set(paths.rules / "default.yaml") == paths.rules / "default.yaml"
    assert paths.resolve_style_profile("formal") == paths.style / "formal.yaml"
    with pytest.raises(ResourceError):
        paths.resolve_rule_set("inexistent")
    assert paths.optional("dictionaries/README.md") is not None
    assert paths.optional("dictionaries/inexistent.txt") is None
    assert paths.language() == paths.resources / "ca"


def test_read_term_list(tmp_path: Path) -> None:
    file = tmp_path / "termes.txt"
    file.write_text("# comentari\ncapital circulant  # nota\n\nPla d'Acció\ncapital circulant\n")
    assert read_term_list(file) == ("capital circulant", "Pla d'Acció")
    with pytest.raises(ResourceError):
        read_term_list(tmp_path / "no.txt")


def test_load_data_formats(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"x": 1}', encoding="utf-8")
    (tmp_path / "b.yml").write_text("x: 2", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    (tmp_path / "d.yaml").write_text("- 1\n- 2", encoding="utf-8")
    (tmp_path / "e.yaml").write_text("", encoding="utf-8")
    (tmp_path / "f.yaml").write_text("x: [", encoding="utf-8")
    assert load_data(tmp_path / "a.json") == {"x": 1}
    assert load_mapping(tmp_path / "b.yml") == {"x": 2}
    assert load_mapping(tmp_path / "e.yaml") == {}
    with pytest.raises(ResourceError):
        load_data(tmp_path / "c.txt")
    with pytest.raises(ResourceError):
        load_mapping(tmp_path / "d.yaml")
    with pytest.raises(ResourceError):
        load_data(tmp_path / "f.yaml")
    with pytest.raises(ResourceError):
        load_data(tmp_path / "absent.yaml")


def test_typed_accessors() -> None:
    data: dict[str, object] = {
        "s": "text",
        "n": 3,
        "f": 1.5,
        "b": True,
        "l": ["a", 1],
        "m": {"k": "v"},
        "ml": [{"k": "v"}],
        "none": None,
    }
    assert as_str(data, "s") == "text"
    assert as_str(data, "n") == "3"
    assert as_str(data, "absent", "x") == "x"
    assert as_float(data, "n") == 3.0
    assert as_float(data, "f") == 1.5
    assert as_int(data, "n") == 3
    assert as_bool(data, "b", False) is True
    assert as_str_list(data, "l") == ("a", "1")
    assert as_str_list(data, "s") == ("text",)
    assert as_str_list(data, "none") == ()
    assert as_mapping(data, "m") == {"k": "v"}
    assert as_mapping(data, "absent") == {}
    assert as_mapping_list(data, "ml") == ({"k": "v"},)
    for call in (
        lambda: as_str(data, "absent"),
        lambda: as_str(data, "b"),
        lambda: as_float(data, "s"),
        lambda: as_float(data, "b"),
        lambda: as_int(data, "f"),
        lambda: as_bool(data, "s", False),
        lambda: as_str_list(data, "m"),
        lambda: as_mapping(data, "s"),
        lambda: as_mapping_list(data, "l"),
    ):
        with pytest.raises(ResourceError):
            call()
