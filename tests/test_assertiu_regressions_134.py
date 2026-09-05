"""Regressions dels casos reals de llenguatge assertiu de la 1.3.4."""

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig


def _rewrite(text: str) -> str:
    pipeline = build_pipeline(
        PipelineConfig(
            level=5,
            assertive_language=True,
            syntax="none",
            use_style=False,
        )
    )
    return pipeline.run(text).text


def test_triple_modalitzacio_es_redueix_sense_convertir_se_en_fet() -> None:
    result = _rewrite("Potser podria ser possible que aquest document fos una còpia posterior.")
    assert "potser podria ser possible" not in result.lower()
    assert "podria" in result.lower()
    assert "és una còpia posterior" not in result.lower()


def test_limitacio_no_inventa_documentacio_per_context_llunya() -> None:
    text = (
        "Aquest document és tardà. "
        "No es pot demostrar que totes les peces formessin part d'un mateix projecte."
    )
    result = _rewrite(text)
    assert "La documentació disponible no permet demostrar" not in result


def test_limitacio_documental_es_permet_quan_la_mateixa_frase_ho_aporta() -> None:
    result = _rewrite("No es pot demostrar que els documents fossin contemporanis.")
    # Pot guanyar l'original o la reformulació segons la resta de la puntuació,
    # però la regla ha de poder generar una alternativa segura; comprovem que
    # el pipeline no altera la força epistemològica.
    assert "demostrar" in result.lower()
    assert "documents" in result.lower()


def test_font_no_es_converteix_en_prova() -> None:
    result = _rewrite("Com detalla Rafael Ramis Barceló, el lul·lisme va gaudir d'una notable protecció.")
    assert "demostra" not in result.lower()
    assert "prova" not in result.lower()
