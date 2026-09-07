"""Composició frase a frase: el motor proposa redaccions, la persona en munta una.

És una manera de treballar diferent de la resta del projecte. A la pantalla
normal, el motor tria i explica per què; aquí no tria: de cada frase del
paràgraf en presenta unes quantes redaccions **el més diferents possible**
entre elles, deixa que qui escriu hi canviï paraules i connectors amb un
desplegable de sinònims i, quan la frase està a punt, la guarda. El paràgraf
final és la suma de les frases que la persona ha donat per bones.

El motor no perd cap garantia pel camí: totes les redaccions que s'ofereixen
han passat els mateixos validadors que qualsevol candidat (preservació
factual, epistemològica, terminològica, gramatical i fragments protegits), i
totes les alternatives dels desplegables surten de recursos locals, ja
flexionades i sense antònims.

Dues coses que aquesta pantalla **no** promet:

- **Tres redaccions sempre.** Una frase curta i sense subordinades pot no
  admetre cap reestructuració segura. Quan és així, es diu; no s'omple la
  llista amb variants inventades ni amb canvis que el motor no faria sol.
- **Triar el sentit.** Els sinònims s'agrupen per sentit i qui edita tria; el
  motor no endevina de quin «peça» o de quin «cavall» parla el text.
"""

from parafrasi_cat.compose.composer import Composer, ParagraphDraft
from parafrasi_cat.compose.options import DraftOption, SentenceDraft, choose_options, distance

__all__ = [
    "Composer",
    "DraftOption",
    "ParagraphDraft",
    "SentenceDraft",
    "choose_options",
    "distance",
]
