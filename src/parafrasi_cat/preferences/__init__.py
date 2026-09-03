"""Preferències explícites de l'autor, feedback manual i jerarquia de prioritats.

- :class:`AuthorPreferences`: fitxer editable (``preferences/author.yml``) amb
  formes preferides i evitades, connectors, longituds de frase i pesos de
  variants;
- :class:`FeedbackStore`: recomptes explícits de les decisions manuals de
  l'autor sobre variants (preferida, acceptable, rebutjada), desats en YAML;
- :class:`PreferenceResolver`: aplica la jerarquia (fragments protegits >
  termes protegits dels diccionaris > formes preferides dels diccionaris >
  preferències explícites de l'autor > empremta estadística > motor);
- :class:`PreferenceEvaluator`: puntua un candidat segons les formes que
  introdueix o elimina i explica cada decisió.

No s'hi entrena cap model: només recomptes i pesos inspeccionables.
"""

from parafrasi_cat.preferences.author import AuthorPreferences
from parafrasi_cat.preferences.evaluator import (
    FormChange,
    PreferenceAssessment,
    PreferenceEvaluator,
)
from parafrasi_cat.preferences.feedback import (
    DEFAULT_FEEDBACK_FILE,
    DEFAULT_PRIOR,
    VERDICTS,
    FeedbackCounts,
    FeedbackStore,
)
from parafrasi_cat.preferences.resolver import (
    FormVerdict,
    PreferenceLevel,
    PreferenceResolver,
    describe_hierarchy,
)

__all__ = [
    "DEFAULT_FEEDBACK_FILE",
    "DEFAULT_PRIOR",
    "VERDICTS",
    "AuthorPreferences",
    "FeedbackCounts",
    "FeedbackStore",
    "FormChange",
    "FormVerdict",
    "PreferenceAssessment",
    "PreferenceEvaluator",
    "PreferenceLevel",
    "PreferenceResolver",
    "describe_hierarchy",
]
