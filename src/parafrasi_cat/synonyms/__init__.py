"""Sinònims per a l'edició assistida: el motor proposa, qui escriu decideix.

Aquest paquet no substitueix mai res pel seu compte. Serveix la pantalla de
composició, on una persona clica una paraula i tria entre les formes
equivalents que el projecte coneix. La diferència amb la resta del motor és
deliberada: una substitució lèxica automàtica exigeix saber de quin sentit es
parla, i això el projecte no ho pot fer sense endevinar. Amb una persona
davant, el sentit el tria ella.

Dues fonts, totes dues locals:

- el **diccionari de sinònims de Softcatalà** (component opcional; els
  antònims no s'importen mai), consultat per :class:`CatalanThesaurus`;
- el que el motor ja sap intercanviar tot sol: classes d'equivalència de
  connectors, grups de variants d'estil i formes preferides dels diccionaris
  terminològics.

:class:`SynonymSuggester` les uneix, flexiona cada proposta perquè encaixi
amb la forma que substitueix i no ofereix mai res que trepitgi un fragment
protegit.
"""

from parafrasi_cat.synonyms.suggester import (
    OptionGroup,
    SynonymOption,
    SynonymSuggester,
    TokenOptions,
    connector_index,
)
from parafrasi_cat.synonyms.thesaurus import (
    RESOURCE_RELATIVE,
    CatalanThesaurus,
    SynonymGroup,
    SynonymMember,
)

__all__ = [
    "RESOURCE_RELATIVE",
    "CatalanThesaurus",
    "OptionGroup",
    "SynonymGroup",
    "SynonymMember",
    "SynonymOption",
    "SynonymSuggester",
    "TokenOptions",
    "connector_index",
]
