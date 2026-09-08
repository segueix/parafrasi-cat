# Nivell 3: implementació i límits comprovats

## Recursos comprovats abans del canvi

- FreeLing: adaptador morfològic preexistent. Afegit adaptador sintàctic local amb columnes explícites i alineament estricte. No instal·lat en aquest entorn; no es presenta com a validat amb l'executable real.
- spaCy català: integració sintàctica preexistent, preservada com a alternativa local. Model absent en aquest entorn.
- Apertium i Softcatalà: adaptadors i motor morfològic existents, reutilitzats. La generació de participis consulta el proveïdor; reserva finita de 12 verbs amb formes explícites.
- UD Catalan-AnCora: importador existent i dues frases anotades de referència per comprovar subarbres i bloquejos. No genera text. Atribució i revisió a tests/fixtures/nivell3-ancora-LICENSE.md.
- LanguageTool local: validador existent, sense ús generatiu. No disponible per a les proves d'aquesta sessió.

## Canvis

Activa ↔ passiva al passat perifràstic amb agent i pacient explícits. Canvia el subjecte sintàctic conservant els papers. Arbres incerts, negació, modalitat, quantificadors, clítics, complements addicionals i verbs fora de l'inventari queden bloquejats.

`structural_change_score` reutilitza el grau estructural existent, s'exporta al JSON i alimenta el bonus existent sense duplicar-lo. Una anada i tornada nominal amb canvi de verb lleuger no rep puntuació estructural neta.

Es reutilitzen els motors de complements, condicionals/concessives i relatives ↔ participis. No s'han implementat conversions generals de coordinació a causalitat, perquè inventarien una relació. Divisió en frases independents i fusió entre frases continuen als nivells superiors, d'acord amb l'abast intern del nivell 3.

La selecció existent demana tres alternatives i reserva espai per a una d'estructural quan n'hi ha. No es garanteixen 2–4 arquitectures diferents per a tota frase; diverses nominalitzacions encara comparteixen arquitectura.

També s'ha corregit un `NameError` preexistent (`counts`) en l'avaluació de paràgrafs, detectat per la bateria completa.

## Activació de FreeLing

`PipelineConfig(syntax="auto")` prova FreeLing abans del parser existent. `syntax="freeling"` el selecciona exclusivament; si no funciona, no inventa cap arbre. Configuració local opcional mitjançant `PARAFRASI_FREELING_COMMAND` i `PARAFRASI_FREELING_CONFIG`. Cap descàrrega en temps d'execució.

La conversió de dependències FreeLing és parcial i conservadora: etiquetes desconegudes i retokenitzacions no alineables bloquegen l'arbre. En mode auto es conserva el recurs a spaCy per a aquestes frases. No és encara una conversió completa de FreeLing a UD.

Referències tècniques:
- https://freeling-user-manual.readthedocs.io/en/v4.1/analyzer/
- https://freeling-user-manual.readthedocs.io/en/v4.1/modules/io/

## Deu sortides reals

Reproducció: `PYTHONPATH=src python scripts/examples_nivell3.py`.
Configuració: regles parafrasi, parser desactivat, validadors interns. Es mostra el candidat acceptat amb més grau estructural (desempat per puntuació), no necessàriament la selecció automàtica final. «Igual» vol dir sense canvi.

| Original | Nivell 2 | Nivell 3 | Canvi estructural |
|---|---|---|---|
| El taller va restaurar la pintura. | Igual | El taller va dur a terme la restauració de la pintura. | 0.3097 |
| La pintura va ser restaurada pel taller. | Igual | La pintura fou restaurada pel taller. | 0.0000 |
| Van analitzar les dades del jaciment. | Igual | Van dur a terme l'anàlisi de les dades del jaciment. | 0.3636 |
| Van fer l’anàlisi de les dades del jaciment. | Igual | Van analitzar les dades del jaciment. | 0.4244 |
| L’equip revisa la datació del sarcòfag. | Igual | L’equip duu a terme la revisió de la datació del sarcòfag. | 0.3450 |
| Van documentar les troballes. | Igual | Van dur a terme la documentació de les troballes. | 0.3564 |
| Tot i la pluja, la porta és oberta. | Igual | La porta és oberta, tot i la pluja. | 0.6654 |
| La porta és oberta, malgrat el fred. | Igual | Malgrat el fred, la porta és oberta. | 0.6656 |
| Com es pot observar, la porta és oberta. | Igual | La porta és oberta, com hom pot observar. | 0.7132 |
| Si plou, la porta és oberta. | Igual | La porta és oberta si plou. | 0.6188 |

## Canvi de veu verificat amb arbres de prova

«El taller va restaurar la pintura.» ↔ «La pintura va ser restaurada pel taller.»
La prova d'integració confirma que el candidat passa els validadors interns al nivell 3 i queda exclòs del nivell 2. L'arbre és una fixture anotada manualment, no una anàlisi real executada per FreeLing o spaCy en aquest entorn.

## Validació

- Bateria completa abans del canvi: 664 passats, 45 fallats, 110 omesos i 6 errors.
- Bateria completa final: 693 passats, 28 fallats, 111 omesos; 7 subtests passats.
- Proves específiques de nivell 3 i dimensions: 15 passades.
- Proves de composició JavaScript: 4 passades.
- Comprovació d'espais del diff: correcta.
- Les omissions inclouen integracions opcionals absents. Els casos de veu i FreeLing s'han comprovat amb fixtures, no amb un executable extern instal·lat.

Fallades restants: expectatives antigues de signatures/diversitat i de metadades de regles, modalització assertiva, selecció/fusió de paràgrafs i un cas de sinònims. El canvi no equival a una reparació completa d'aquestes àrees.

La bateria no és verda: els errors restants s'han de revisar abans d'afirmar estabilitat global. No s'han canviat expectatives de proves antigues per amagar-los.
