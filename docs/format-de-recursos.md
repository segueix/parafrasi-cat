# Format dels recursos i de la configuració

Tots els fitxers de dades són YAML (o JSON equivalent) en UTF-8 i tenen una
clau `description` a l'arrel. Es carreguen amb `parafrasi_cat.resources`.

## `resources/ca/lexicon/abreviatures.yaml`

```yaml
description: ...
abbreviations: [sr, sra, dr, pàg, ...]   # sense punt, en minúscules
```

S'afegeixen a `parafrasi_cat.analyzer.DEFAULT_ABBREVIATIONS`.

## `resources/ca/lexicon/modalitat.yaml`

```yaml
description: ...
hedges: [potser, probablement, ...]        # atenuadors: no poden disminuir
certainty: [sens dubte, evidentment, ...]  # certesa: no pot augmentar
negation: ["no", mai, cap, ...]            # negació: recompte idèntic
negation_exceptions: [no obstant això, ...]  # locucions que no neguen
```

## `resources/ca/connectors/connectors.yaml`

```yaml
description: ...
groups:
  - function: contrast
    connectors:
      - {form: però, register: neutre}
      - {form: tanmateix, register: formal}
```

Ús actual: densitat de connectors a les mètriques d'estil.

## `resources/ca/transformations/*.yaml` (diccionaris de substitució)

```yaml
description: ...
transformation_type: lexical       # tipus per defecte de les entrades
default_semantic_risk: low
default_confidence: 0.8
entries:
  - source: gairebé                 # paraula o locució (coincidència sencera, sense majúscules)
    target: quasi
    note: sinònims plens            # opcional, s'afegeix a l'explicació
    semantic_risk: low              # opcional
    confidence: 0.9                 # opcional
    transformation_type: lexical    # opcional (lexical | connector | ...)
```

## `resources/ca/morphology/formes.yaml`

Vegeu `resources/ca/morphology/README.md`.

## `resources/style/<nom>.yaml` (perfils d'estil)

```yaml
name: formal
description: ...
sentence_length: {target_mean: 22, tolerance: 10}
formality: 0.8                    # 0-1
preferred_connectors: [tanmateix, ...]
avoided_words: [o sigui, ...]
max_change_ratio: 0.3
```

## `rules/<nom>.yaml` (conjunts de regles)

Vegeu `rules/README.md`.

## `dictionaries/*.txt`

Un terme per línia; `#` inicia un comentari. Vegeu `dictionaries/README.md`.

## Configuració de la canonada (`--config`)

```yaml
home: ../                          # opcional; arrel amb resources/, rules/, dictionaries/
language: ca
rule_set: exemple-lexic            # nom dins de rules/ o ruta
style_profile: formal              # nom dins de resources/style/ o ruta
protected_terms: [capital circulant]
protected_terms_files: [els-meus-termes.txt]
max_semantic_risk: low             # opcional; per defecte el del conjunt de regles
min_confidence: 0.6                # opcional; per defecte la del conjunt de regles
scoring:
  transformation_gain: 1.0
  semantic_risk: 1.0
  style_distance: 0.5
  max_transformations: 3
max_transformations_per_sentence: 3
max_candidates_per_sentence: 20
length_ratio: {min: 0.6, max: 1.6}
use_style: true
```

Les rutes relatives es resolen respecte del directori del fitxer de
configuració. Les opcions del CLI tenen prioritat sobre el fitxer.
