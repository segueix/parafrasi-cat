"""Adaptadors d'eines externes opcionals, sempre locals.

Cap adaptador no és obligatori: si l'eina no hi és, el motor continua amb els
seus components interns. Cap adaptador no envia text fora de l'ordinador.
"""

from parafrasi_cat.adapters.languagetool import (
    DEFAULT_BLOCKING_CATEGORIES,
    DEFAULT_BLOCKING_ISSUE_TYPES,
    ClassifiedMatch,
    LanguageToolClient,
    LanguageToolInstallation,
    LanguageToolMatch,
    LanguageToolValidator,
    MatchSeverity,
    classify,
    find_installation,
    find_java,
    is_blocking,
)
from parafrasi_cat.adapters.status import (
    ComponentStatus,
    LinguisticMode,
    LinguisticResources,
    resources_status,
)

__all__ = [
    "DEFAULT_BLOCKING_CATEGORIES",
    "DEFAULT_BLOCKING_ISSUE_TYPES",
    "ClassifiedMatch",
    "ComponentStatus",
    "LanguageToolClient",
    "LanguageToolInstallation",
    "LanguageToolMatch",
    "LanguageToolValidator",
    "LinguisticMode",
    "LinguisticResources",
    "MatchSeverity",
    "classify",
    "find_installation",
    "find_java",
    "is_blocking",
    "resources_status",
]
