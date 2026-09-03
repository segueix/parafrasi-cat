# Diccionaris de l'usuari

Fitxers de text pla (UTF-8, un terme per línia, `#` inicia un comentari) que
la canonada carrega automàticament si existeixen.

| Fitxer | Efecte |
|---|---|
| `termes_protegits.txt` | Cap regla pot modificar aquests termes (coincidència sense distingir majúscules). |
| `noms_propis.txt` | Noms propis coneguts, protegits amb coincidència exacta (distingint majúscules). Complementa l'heurística de majúscules. |

També es poden indicar termes protegits des del CLI (`--protect TERME`,
`--protect-file FITXER`) o des de la configuració (`protected_terms`,
`protected_terms_files`).

Els diccionaris grans (sinònims, formes flexionades) van a `resources/ca/`.
