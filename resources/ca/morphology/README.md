# Recursos morfològics

Aquest directori conté les dades que fa servir el paquet `parafrasi_cat.morphology`.

## Fitxers

| Fitxer | Contingut | Estat |
|---|---|---|
| `formes.yaml` | Formes flexionades amb lema i trets (mostra) | Carregat per `DictionaryMorphology` |

## Format de `formes.yaml`

```yaml
entries:
  - form: cases      # forma tal com apareix al text
    lemma: casa      # lema
    pos: noun        # categoria: noun, verb, adj, adv, det, pron, adp, conj, num, propn
    gender: f        # m | f
    number: pl       # sg | pl
    person: "3"      # 1 | 2 | 3 (verbs)
    tense: pres      # pres | past | impf | fut | cond (verbs)
    mood: ind        # ind | subj | imp | inf | ger | part (verbs)
```

## Fonts previstes

Per a un diccionari morfològic complet caldrà importar dades d'un recurs
extern. Abans d'integrar-ne cap cal revisar-ne la llicència; vegeu
`docs/eines-externes-opcionals.md`. Els fitxers importats s'han de generar
amb un script reproduïble, no copiar a mà.
