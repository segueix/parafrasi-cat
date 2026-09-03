"""Canonada de processament: anàlisi → protecció → regles → candidats → validació → selecció."""

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.modes import (
    CONSERVATIVE,
    DEEP,
    MODES,
    ModeSettings,
    RewriteMode,
    apply_mode,
    level_label,
    mode_settings,
)
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    ParaphraseResult,
    RejectedProposal,
    SentenceResult,
)

__all__ = [
    "CONSERVATIVE",
    "DEEP",
    "MODES",
    "EvaluatedCandidate",
    "ModeSettings",
    "ParaphraseResult",
    "Pipeline",
    "PipelineConfig",
    "RejectedProposal",
    "RewriteMode",
    "SentenceResult",
    "apply_mode",
    "build_pipeline",
    "level_label",
    "mode_settings",
]
