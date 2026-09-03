# Conjunts de regles

Cada fitxer YAML d'aquest directori defineix un *conjunt de regles*: quines
regles s'activen, amb quins paràmetres, i quins llindars de risc i confiança
s'apliquen a totes les transformacions proposades.

| Fitxer | Descripció |
|---|---|
| `default.yaml` | Cap regla activa (comportament identitat). És el que fa servir el CLI si no s'indica `--rules`. |
| `exemple-lexic.yaml` | Activa `lexical.substitution` amb el diccionari d'exemple. |

## Format

```yaml
name: nom-del-conjunt
description: text lliure
max_semantic_risk: low      # none | low | medium | high
min_confidence: 0.6         # entre 0 i 1
rules:
  - id: lexical.substitution      # identificador únic dins del conjunt
    type: lexical.substitution    # tipus registrat a RuleRegistry (opcional, = id)
    enabled: true
    params:                       # paràmetres propis del tipus de regla
      source: resources/ca/transformations/substitucions_lexiques.yaml
```

Les rutes dels paràmetres es resolen respecte de l'arrel del projecte.

## Tipus de regla disponibles

| Tipus | Paràmetres | Descripció |
|---|---|---|
| `lexical.substitution` | `source` | Substitueix paraules o locucions per equivalents d'un diccionari YAML/JSON. |

Els tipus nous es registren a `parafrasi_cat.rules.registry.default_registry`.
