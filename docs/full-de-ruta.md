# Full de ruta

## Fase 1: esquelet i garanties

- [x] Arquitectura modular amb tipatge estricte.
- [x] `Transformation` i `ProtectedSpan` amb tots els camps previstos.
- [x] Analitzador basat en regles (frases i tokens amb offsets exactes).
- [x] Detectors de fragments protegits (dates, xifres, números romans,
      cometes, citacions, noms propis, termes d'usuari).
- [x] Validadors d'invariants de contingut.
- [x] Generació de candidats, puntuació composta i selecció determinista.
- [x] Perfils d'estil i mètriques estilomètriques bàsiques.
- [x] Regla de substitució lèxica basada en diccionari (com a model).
- [x] Canonada mínima: per defecte, retorna el text sense modificar.
- [x] CLI, configuració YAML/JSON, tests automatitzats, documentació.

## Fase 2: lèxic i connectors

- Diccionari de sinònims amb categoria i registre (`sinonims.yaml`), generat
  amb scripts reproduïbles a partir de recursos amb llicència compatible.
- Regla de connectors: substitució dins de la mateixa funció discursiva,
  sensible al registre del perfil d'estil.
- Concordança: comprovar gènere i nombre amb `DictionaryMorphology` abans de
  substituir un nom o un adjectiu.
- Ampliar `modalitat.yaml` i afegir un validador de quantificadors
  («tots», «alguns», «cap») i de temps verbal.

## Fase 3: sintaxi

- Transformacions sintàctiques segures: canvi d'ordre de circumstancials
  inicials, coordinació ↔ juxtaposició, divisió de frases llargues per
  connector.
- Adaptador opcional d'un analitzador morfosintàctic (vegeu
  `docs/eines-externes-opcionals.md`) per a les regles que necessitin
  categories gramaticals.

## Fase 4: estil de l'autor

- Estimació completa del perfil a partir de `corpus/author/` (riquesa lèxica,
  connectors preferits, longitud, puntuació).
- Puntuació que apropi el resultat a l'estil de l'autor sense allunyar-se del
  contingut.
- Informe comparatiu abans/després amb totes les mètriques.

## Fase 5: validació, puntuació i selecció

- Validació factual, terminològica i epistemològica de cada candidat.
- Puntuació multidimensional i selecció determinista.

## Fase 6: diccionaris, preferències i feedback

- Diccionaris terminològics editables per projecte, amb termes protegits.
- Preferències explícites de l'autor i jerarquia de prioritats.
- Feedback manual com a recomptes explícits, sense cap model entrenat.

## Fase 7 (actual): interfície local i versió funcional

- Interfície web local sobre la canonada existent.
- Modes conservador i de reredacció profunda.
- Registre de traçabilitat local i opcional.

## Sempre

- Cap LLM, cap servei extern, cap telemetria.
- Cada regla nova ha d'arribar amb tests que demostrin que respecta els
  fragments protegits i els invariants.
