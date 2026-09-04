"""Interfície local: servei i servidor web sobre la canonada existent.

Tot el processament s'executa a l'ordinador que engega el servidor: la pàgina
no carrega cap recurs extern i no s'envia cap text a Internet. Per defecte el
servidor es lliga a l'amfitrió local; amb el mode de xarxa local
(:mod:`parafrasi_cat.web.auth`) també l'obre un altre dispositiu de la mateixa
LAN, amb codi d'accés i sessió, i el text hi circula per la xarxa local.

La interfície no afegeix cap capacitat lingüística nova: només exposa el que
ja fan la canonada, els diccionaris, les preferències i el feedback, i el
resultat és idèntic en tots dos modes.
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
