"""parafrasi-cat: motor local de reredacció i parafraseig en català basat en regles.

Principi fonamental: el contingut original és intocable. El motor només pot
canviar la forma del text; mai no inventa informació, ni altera dates, noms,
xifres, números romans, citacions ni terminologia protegida.

Garanties de funcionament:

- No fa servir cap model generatiu ni cap LLM.
- No es connecta a Internet ni envia text a cap servei extern.
- No recull telemetria.
"""

from parafrasi_cat.core.spans import Span
from parafrasi_cat.core.transformation import SemanticRisk, Transformation, TransformationType
from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import ParaphraseResult
from parafrasi_cat.protected.spans import ProtectedSpan, ProtectionKind

__version__ = "1.3.2"

__all__ = [
    "ParaphraseResult",
    "Pipeline",
    "PipelineConfig",
    "ProtectedSpan",
    "ProtectionKind",
    "SemanticRisk",
    "Span",
    "Transformation",
    "TransformationType",
    "__version__",
    "build_pipeline",
    "paraphrase",
]


def paraphrase(text: str, config: PipelineConfig | None = None) -> ParaphraseResult:
    """Drecera: construeix la canonada amb ``config`` i processa ``text``."""
    return build_pipeline(config).run(text)
