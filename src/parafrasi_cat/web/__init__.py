"""Interfície local: servei i servidor web sobre la canonada existent.

Tot s'executa a l'ordinador de l'usuari: el servidor es lliga a l'amfitrió
local, la pàgina no carrega cap recurs extern i no s'envia cap text enlloc.
La interfície no afegeix cap capacitat lingüística nova: només exposa el que
ja fan la canonada, els diccionaris, les preferències i el feedback.
"""

from parafrasi_cat.web.history import HistoryEntry, HistoryLog
from parafrasi_cat.web.server import DEFAULT_HOST, DEFAULT_PORT, build_server, serve
from parafrasi_cat.web.service import (
    DiffPart,
    FeedbackRequest,
    RewriteRequest,
    RewriteService,
    word_diff,
)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DiffPart",
    "FeedbackRequest",
    "HistoryEntry",
    "HistoryLog",
    "RewriteRequest",
    "RewriteService",
    "build_server",
    "serve",
    "word_diff",
]
