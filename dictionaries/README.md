# Diccionaris del projecte

## Diccionaris terminològics (`*.yml`)

Cada fitxer YAML és un diccionari editable que s'activa explícitament, sol o
combinat amb d'altres:

```
parafrasi-cat rewrite text.txt --dictionary historia --dictionary noms_propis
parafrasi-cat --dictionary dictionaries/escacs.yml "El bisbe ataca el peó."
```

o des de la configuració (`dictionaries: [historia, medieval]`). Un nom es
resol a `dictionaries/<nom>.yml`; també s'admet una ruta.

| Fitxer | Contingut |
|---|---|
| `general.yml` | Locucions de registre formal, independents del tema. |
| `historia.yml` | Història i història de l'art (arqueologia, patrimoni). |
| `medieval.yml` | Història medieval (institucions, feudalisme). |
| `escacs.yml` | Escacs (peces, jugades). |
| `noms_propis.yml` | Noms propis protegits, amb formes acceptades. |

### Format

```yaml
description: Terminologia d'història de l'art.
language: ca
confidence: 0.8            # opcional: confiança de les substitucions (0-1)
entries:
  - term: sarcòfag           # terme canònic (obligatori)
    preferred: [sarcòfag]    # formes que cal fer servir (per defecte, el terme)
    accepted: [sarcòfag funerari]   # formes tolerades: ni es proposen ni es penalitzen
    avoid: [fèretre]         # formes a evitar: es proposen substituir per la preferida
    protected: true          # cap regla pot modificar el terme ni les formes conservades
    pos: nom                 # categoria gramatical (informativa)
    notes: "No substituir en contextos arqueològics."
```

Efectes:

- **`protected`**: el terme i les seves formes preferides i acceptades passen
  a ser fragments protegits (com els de `termes_protegits.txt`): cap regla
  estilística no els pot modificar i els validadors ho comproven de nou.
- **`avoid` → `preferred`**: la regla `dictionary.preferred_form` proposa
  substituir cada forma a evitar per la primera forma preferida, mai dins
  d'un fragment protegit. Qualsevol candidat que introdueixi una forma a
  evitar queda penalitzat a la puntuació; un que introdueixi una forma
  preferida hi guanya.
- **`accepted`**: neutres.

Amb diversos diccionaris actius, la protecció és acumulativa i, si dos
diccionaris classifiquen una mateixa forma de manera diferent, mana el primer
de la llista d'activació (els conflictes es poden llistar amb
`DictionarySet.conflicts()`).

Jerarquia de prioritats (de més a menys): fragments protegits explícitament
→ termes protegits dels diccionaris → formes preferides dels diccionaris →
preferències explícites de l'autor (`preferences/author.yml` i feedback) →
empremta estadística → preferències generals del motor.

## Llistes de text pla (`*.txt`)

Fitxers UTF-8 amb un terme per línia (`#` inicia un comentari) que la
canonada carrega automàticament si existeixen.

| Fitxer | Efecte |
|---|---|
| `termes_protegits.txt` | Cap regla pot modificar aquests termes (coincidència sense distingir majúscules). |
| `noms_propis.txt` | Noms propis coneguts, protegits amb coincidència exacta (distingint majúscules). Complementa l'heurística de majúscules. |

També es poden indicar termes protegits des del CLI (`--protect TERME`,
`--protect-file FITXER`) o des de la configuració (`protected_terms`,
`protected_terms_files`).

Els diccionaris grans (sinònims, formes flexionades) van a `resources/ca/`.
