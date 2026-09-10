# Fallades conegudes de la bateria

Classificació de les proves que fallen, per **causa**, no per fitxer. Serveix per
decidir què s'arregla i què no, i per no tornar a diagnosticar el mateix.

Punt de partida: 23 fallades a `main` (`151ab02`). Aquesta entrega n'ha resolt
quatre i n'ha convertit una en una fallada nova i informativa (vegeu el grup B).

| Grup | Causa | Proves | Efecte visible | Prioritat |
| --- | --- | --- | --- | --- |
| A | Fusió de paràgrafs retirada a posta | 6 | Cap: el motor fa el que ha de fer | Alta (decisió, no codi) |
| B | Piles de modalització que no es redueixen | 1 | Sí: «Llenguatge assertiu» no toca res | Alta |
| C | El sintagma nominal es menja el verb | 2 | Sí: dues regles no s'apliquen mai | Mitjana |
| D | Signatures i comptes de candidats | 7 | Per determinar | Mitjana |
| E | Recursos de prova absents | 1 | Cap | Baixa |
| F | Encara no determinada | 2 | Per determinar | Baixa |

---

## A. Fusió de paràgrafs retirada a posta — *expectativa obsoleta*

**Proves.** `test_robustesa.py` (4: `test_the_fusion_is_a_candidate_when_nothing_limits_the_length`,
`test_level_5_respects_the_authors_maximum_sentence_length`,
`test_a_short_sentence_fingerprint_avoids_excessive_fusion`,
`test_a_long_sentence_fingerprint_keeps_the_fusion_available`),
`test_v1_release.py::test_level_five_produces_paragraph_candidates`,
`test_cas_altoviti.py::test_explanations_and_json`.

**Exemple mínim.**

```
La primera referència itàlica és el monument funerari d'Oddo Altoviti, encarregat el 1507
i finalitzat el 1516. En aquest sarcòfag fet per l'escultor Benedetto da Rovezzano hi ha
la presència de dos cranis...
```

Les proves esperen la fusió `, i en aquest sarcòfag`. Cap estratègia no hi arriba,
i cap no hi ha d'arribar:

* `frases_curtes` demana `max_words: 16` en total i `max_words_each: 8`; les dues
  frases en fan 19 i 30. A més, «En aquest» és a `skip_if_second_starts_with`.
* `aposicio_anaforica` demana `nominal_fragment: true`; la segona frase és una
  oració sencera.

El comentari de `resources/ca/transformations/fusio.yaml` diu que l'estretor és
**deliberada**: «No es fusionen simples fronteres “. Però” → “, però”… Són canvis
de puntuació o d'enllaç massa petits per comptar com a reredacció profunda.» La
fusió que les proves esperen és exactament una d'aquestes fronteres.

**Efecte visible.** Cap. El motor es comporta com el fitxer de regles declara.

**Què cal decidir** (no és una correcció de codi): o bé les estratègies es tornen
a eixamplar a posta —i llavors cal dir amb quin criteri una frontera «. En aquest»
sí que compta com a reredacció—, o bé les sis proves s'han de reescriure perquè
afirmin el comportament que ara es vol. Aquí no s'ha fet ni una cosa ni l'altra:
canviar-les perquè passin amagaria la pregunta.

## B. Piles de modalització que no es redueixen — *error real*

**Prova.** `test_assertiu_regressions_134.py::test_triple_modalitzacio_es_redueix_sense_convertir_se_en_fet`.

**Exemple mínim.**

```
Potser podria ser possible que aquest document fos una còpia posterior.
→ (sense canvis, amb parser i sense)
```

Cap regla `assertiu.*` no proposa res. `assertiu.normalitza_modalitzacio`
(motor `epistemic_normalize`) hauria de reduir la pila redundant a un sol
marcador de la mateixa classe epistemològica, i no ho fa. La mateixa regla és
també l'única sense cap exemple positiu declarat, cosa que fa fallar
`test_regles_definicions.py::test_every_rule_has_complete_metadata`.

**Efecte visible.** Sí: amb l'opció «Llenguatge assertiu» activada, un text amb
tres modalitzacions encadenades surt igual que ha entrat.

**Per què no s'arregla aquí.** És una regla epistemològica: tocar-la vol dir
tocar la certesa del que s'afirma, i això demana una entrega pròpia amb la seva
bateria. No és petita ni està directament relacionada amb la correcció d'aquesta.

**Nota.** Aquestes quatre proves fallaven totes per una causa mecànica —el
comodí `pipeline.run(text).text`, quan el camp es diu `output_text`— i no
arribaven ni a executar la seva asserció. Corregit el comodí, tres passen i la
quarta és la fallada real que es descriu aquí. És l'única fallada «nova» de
l'entrega, i és una troballa, no una regressió.

## C. El sintagma nominal es menja el verb — *error real*

**Proves.** `test_regles_definicions.py::test_rule_examples[ordre.connector_inicial_a_medial]`
i, abans d'aquesta entrega, `test_rule_examples[nominal.verb_a_nom]` (ja resolta,
vegeu més avall).

**Exemple mínim.**

```
Per tant, la hipòtesi continua oberta.   →  (cap proposta)
```

`ordre.connector_inicial_a_medial` demana `{np: true}` per al subjecte i un
`{seq}` per a la resta. `NounPhraseElement.ends` s'atura davant d'un verb
conjugat, però el conjecturador morfològic llegeix «continua», «ocupa» i
«revisa» com a **noms** (confiança 0,2), de manera que el sintagma es menja el
verb i la resta de la frase, i el patró no pot encaixar mai. `ends` només
retorna el final màxim i les fronteres de preposició: no ofereix cap final més
curt on el motor pugui reintentar.

**Efecte visible.** Sí: la regla no s'aplica mai. La família «connector inicial
→ medial» és morta.

**Per què no s'arregla aquí.** Les tres sortides possibles —fer que
`is_finite_verb` consulti l'arbre, fer que `NounPhraseElement` ofereixi finals
més curts, o exigir el parser a la regla— toquen el nucli de l'aparellador de
patrons, que fan servir gairebé totes les regles. No és una correcció petita.

**Resolta en aquesta entrega:** `nominal.verb_a_nom` tenia una causa diferent
i sí que era petita (vegeu el `CHANGELOG`): l'article elidit «L'» de «L'equip»
és un `CLITIC` per a l'analitzador de text, i la guarda de pronoms febles del
motor de nominalització el prenia per un pronom. Ara l'arbre els distingeix
(`DET` contra `PRON`) i, sense parser, el bloqueig es manté com era.

## D. Signatures i comptes de candidats — *per determinar*

**Proves.** `test_arquitectura_paragraf.py::test_the_generator_keeps_structural_signatures_over_verbal_combinations`,
`test_reredaccio_profunda.py::test_the_generator_keeps_one_candidate_per_signature`,
`test_candidats_v2.py` (2), `test_cerca_candidats.py` (2),
`test_blocs_circumstancials.py::test_it_covers_sentences_that_had_no_alternative`.

**Exemple mínim.** Les assercions són de la forma `assert 'REORDER' in
{'MULTI_TRANSFORM(LEXICAL+REORDER)', 'ORIGINAL'}` o `assert 2 == 3`: esperen una
signatura simple i en surt una de composta, o esperen un candidat més dels que hi
ha.

**Diagnòstic parcial.** Totes apunten al mateix lloc —com el generador compon
signatures i quants candidats en deixa per signatura— i és versemblant que
comparteixin una sola causa. Falta comprovar si el canvi de signatures va ser
deliberat (com al grup A) o si el generador n'ha perdut pel camí. Fins que això
no estigui clar, no es pot dir si afecta el text generat.

## E. Recursos de prova absents — *recurs absent*

**Prova.** `test_composicio.py::test_the_senses_are_kept_apart` (`StopIteration`).

El diccionari de sinònims de prova es construeix al vol amb l'importador real i
no conté cap entrada per a «casa» amb dos sentits separats. Cap efecte sobre el
producte.

## F. Encara no determinada

`test_interficie.py::test_conservative_keeps_the_original_when_nothing_is_clearly_safe`
i `test_regles_definicions.py::test_every_rule_has_complete_metadata`. La segona
depèn del grup B (l'exemple positiu que falta és el de
`assertiu.normalitza_modalitzacio`); la primera no s'ha diagnosticat.

---

## Com reproduir el diagnòstic

```bash
python -m pytest tests/test_robustesa.py tests/test_v1_release.py -q      # grup A
python -m pytest tests/test_assertiu_regressions_134.py -q                # grup B
python -m pytest tests/test_regles_definicions.py -q                      # grups C i F
```
