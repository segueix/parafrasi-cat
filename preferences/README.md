# Preferències explícites de l'autor

| Fitxer | Contingut |
|---|---|
| `author.yml` | Preferències editables: formes preferides i evitades, connectors, longituds de frase, pesos de variants. |
| `feedback.yml` | Recomptes del feedback manual (`preferred`, `acceptable`, `rejected`) per variant. |

```
parafrasi-cat rewrite text.txt --style style/author.json \
  --dictionary dictionaries/historia.yml --preferences preferences/author.yml
parafrasi-cat feedback preferred "obra de"
parafrasi-cat feedback rejected "fet per"
parafrasi-cat feedback show
```

## `author.yml`

```yaml
prefer: ["així com", "per tant"]        # pes 1
avoid: ["a nivell de", "en base a"]     # pes 0
preferred_connectors: [tanmateix]       # pes 1
preferred_sentence_length: 22           # substitueix la longitud objectiu del perfil d'estil
max_sentence_length: 45                 # un candidat amb una frase més llarga rep −1
preferred_variants:                     # pes 0-1 de cada variant equivalent
  "obra de": 1.0
  "fet per": 0.4
  "realitzat per": 0.7
feedback: feedback.yml                  # opcional, relatiu a aquest fitxer
```

Per a cada forma coneguda, el motor compara quantes vegades apareix a
l'original i al candidat: introduir una forma aporta el seu pes amb signe
(2·pes − 1, entre −1 i +1) i eliminar-la, el contrari. La suma, limitada a
[−1, 1] i multiplicada pel pes `scoring.preferences` (0,5 per defecte),
s'afegeix a la puntuació global, i cada decisió s'explica a l'informe.

## `feedback.yml`

```yaml
prior: 3
variants:
  obra de: {preferred: 4, acceptable: 2, rejected: 0}
  fet per: {preferred: 0, acceptable: 1, rejected: 3}
```

El pes d'una variant és la mitjana d'aprovació (preferida = 1, acceptable =
0,5, rebutjada = 0) suavitzada amb `prior` observacions neutres:
`(preferred + 0,5·acceptable + 0,5·prior) / (total + prior)`. Amb `prior`
3, una única decisió mou el pes de 0,5 a 0,625 (o a 0,375); calen diverses
decisions coherents per acostar-se a 1 o a 0. No s'hi entrena cap model: el
fitxer es pot llegir, editar i versionar.

## Jerarquia

1. fragments protegits explícitament;
2. termes protegits dels diccionaris;
3. formes preferides, acceptades o a evitar dels diccionaris;
4. preferències explícites de l'autor (`author.yml` i, després, el feedback);
5. empremta estadística (`style/<autor>.json`);
6. preferències generals del motor.

Una regla estilística mai no pot sobreescriure un terme protegit, i una
forma amb preferència explícita (nivells 1-4) no es torna a valorar amb
l'empremta estadística.
