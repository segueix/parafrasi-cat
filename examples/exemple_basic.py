"""Exemple d'ús de l'API de parafrasi-cat.

Executeu-lo des de l'arrel del projecte::

    python examples/exemple_basic.py
"""

from __future__ import annotations

from pathlib import Path

from parafrasi_cat import PipelineConfig, build_pipeline

TEXT = (Path(__file__).parent / "text_exemple.txt").read_text(encoding="utf-8")


def main() -> None:
    # 1. Canonada per defecte: cap regla activa, el text no canvia.
    pipeline = build_pipeline()
    result = pipeline.run(TEXT)
    assert result.output_text == TEXT
    print("Fragments protegits detectats amb la configuració per defecte:")
    for protected in result.protected_spans:
        print("  ", protected.describe())

    # 2. Canonada amb el conjunt de regles d'exemple.
    config = PipelineConfig(rule_set="exemple-lexic", protected_terms=("informe anual",))
    result = build_pipeline(config).run(TEXT)
    print()
    print(result.explain())
    print()
    print("Text resultant:")
    print(result.output_text)


if __name__ == "__main__":
    main()
