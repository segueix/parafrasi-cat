"""Canonada de processament: anàlisi → protecció → regles → candidats → validació → selecció."""

from parafrasi_cat.pipeline.builder import build_pipeline
from parafrasi_cat.pipeline.config import PipelineConfig
from parafrasi_cat.pipeline.pipeline import Pipeline
from parafrasi_cat.pipeline.result import (
    EvaluatedCandidate,
    ParaphraseResult,
    RejectedProposal,
    SentenceResult,
)

__all__ = [
    "EvaluatedCandidate",
    "ParaphraseResult",
    "Pipeline",
    "PipelineConfig",
    "RejectedProposal",
    "SentenceResult",
    "build_pipeline",
]
