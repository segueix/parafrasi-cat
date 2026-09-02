# Principis de preservació del contingut

**El contingut original és intocable.** El motor pot canviar la forma d'una
frase, però mai el que diu. Aquest document enumera les prohibicions i com
el codi les fa complir.

## Prohibicions i mecanismes

| El motor no pot... | Mecanisme que ho impedeix |
|---|---|
| Inventar informació | Cap regla no genera text lliure: només substitueix o reordena fragments existents amb equivalents registrats. No hi ha cap model generatiu. |
| Afegir conclusions | Ídem; a més, `length_ratio` rebutja candidats molt més llargs. |
| Eliminar matisos | `modality` rebutja candidats amb menys atenuadors; `length_ratio` rebutja candidats molt més curts. |
| Alterar dates | `DateDetector` protegeix les dates; `protected_spans` comprova que es conserven. |
| Alterar noms | `ProperNounDetector` + `dictionaries/noms_propis.txt`; `protected_spans`. |
| Alterar xifres | `NumberDetector`; `numeric_invariants` compara els multiconjunts de xifres. |
| Alterar números romans | `RomanNumeralDetector`; `numeric_invariants`. |
| Alterar citacions | `CitationDetector` (referències) i `QuotedTextDetector` (text literal); `protected_spans`. |
| Convertir una hipòtesi en certesa | `modality`: els atenuadors no poden disminuir ni els marcadors de certesa augmentar. |
| Canviar la negació | `negation`: el recompte de marcadors de negació ha de ser idèntic. |
| Canviar terminologia protegida | `UserTermDetector` amb `--protect`, `protected_terms` o `dictionaries/termes_protegits.txt`. |

## Dues línies de defensa

1. **Abans de generar candidats.** La canonada descarta qualsevol
   transformació que toqui un fragment protegit, que superi el risc semàntic
   màxim o que no arribi a la confiança mínima. Les regles ben escrites ja
   ho comproven, però la canonada no s'hi refia.
2. **Després de generar candidats.** Els validadors comproven cada candidat
   sencer contra la frase original. Un candidat amb un sol error queda
   rebutjat i no es puntua. Si tots els candidats fallessin (cosa que només
   passaria amb un validador defectuós), es conserva l'original.

Els tests `tests/test_pipeline.py::test_validators_are_second_line_of_defense`
i `test_pipeline_without_validators_still_blocks_protected` demostren les
dues línies amb una regla deliberadament perillosa.

## Risc semàntic

Cada transformació porta un `SemanticRisk`:

| Nivell | Pes | Significat |
|---|---|---|
| `none` | 0 | Canvi purament formal (puntuació, ordre sense ambigüitat) |
| `low` | 0,25 | Sinònims plens o connectors de la mateixa funció |
| `medium` | 0,6 | Equivalents amb matís de registre o de context |
| `high` | 1 | Canvis que poden alterar el sentit en alguns contextos |

El conjunt de regles fixa `max_semantic_risk` (per defecte `low`). El motor
és conservador per disseny: davant del dubte, no canvia res.

## Explicabilitat

Cada transformació porta `explanation`, i `ParaphraseResult.explain()` mostra
per a cada frase què s'ha canviat, què s'ha descartat i per què. L'opció
`--explain` del CLI i `--json` exposen tota aquesta informació.

## Limitacions conegudes de la fase 1

- Les heurístiques de noms propis depenen de les majúscules: un nom d'una
  sola paraula al començament de frase no es detecta si no és al diccionari
  de noms propis.
- Els marcadors de negació i modalitat són llistes tancades; es poden ampliar
  a `resources/ca/lexicon/modalitat.yaml`.
- Sobreprotegir és segur: un fals positiu només impedeix un canvi. Per això
  els detectors prefereixen protegir de més que de menys.
