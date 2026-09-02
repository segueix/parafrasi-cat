# parafrasi-cat

Motor **local** de reredacció i parafraseig en català basat en regles
lingüístiques explícites. No fa servir cap LLM, cap API generativa ni cap
servei extern: tot s'executa a l'ordinador de l'usuari i cap text no en surt
mai.

> **Estat: fase 1 (esquelet).** L'arquitectura, les interfícies, la canonada
> mínima, el CLI i els tests ja hi són. Amb la configuració per defecte el
> motor analitza i protegeix el text, però el retorna **sense modificar**.
> Un conjunt de regles d'exemple mostra el circuit complet de transformació.

## Principi fonamental

**El contingut original és intocable.** El sistema pot canviar la *forma*
d'una frase, però no pot:

- inventar informació ni afegir conclusions;
- eliminar matisos;
- alterar dates, noms, xifres, números romans ni citacions;
- convertir una hipòtesi en una certesa;
- canviar terminologia protegida.

Cada prohibició té un mecanisme concret al codi (detectors de fragments
protegits i validadors d'invariants). Vegeu
[`docs/principis-de-preservacio.md`](docs/principis-de-preservacio.md).

## Garanties

| Garantia | Com es compleix |
|---|---|
| Cap LLM ni model generatiu | Només regles, diccionaris i heurístiques deterministes. |
| Cap connexió a Internet | L'únic paquet extern és PyYAML. Un test comprova que el codi no importa mòduls de xarxa. |
| Cap telemetria ni enviament de textos | No hi ha cap codi de xarxa; tot és local. |
| Explicabilitat | Cada `Transformation` porta una explicació; `--explain` i `--json` la mostren. |
| Determinisme | Mateixa entrada + mateixa configuració = mateix resultat, sempre. |

## Instal·lació

Requereix Python 3.11 o superior.

```bash
git clone <url-del-repositori> parafrasi-cat
cd parafrasi-cat
pip install -e ".[dev]"
```

## Ús ràpid

```bash
# Per defecte: cap regla activa, el text es retorna igual
parafrasi-cat "El 12 de gener de 2020, Joan Maragall va publicar «Elogi de la paraula»."

# Amb el conjunt de regles d'exemple i informe explicatiu (a la sortida d'error)
parafrasi-cat --rules exemple-lexic --explain "Gairebé sempre plou, tot i que avui no."
# → Quasi sempre plou, encara que avui no.

# Des d'un fitxer, resultat en JSON amb tota la traça
parafrasi-cat --input examples/text_exemple.txt --rules exemple-lexic --json

# Protegir terminologia pròpia
parafrasi-cat --rules exemple-lexic --protect "capital circulant" --protect-file termes.txt "…"

# Amb un fitxer de configuració (YAML o JSON)
parafrasi-cat --config examples/config_exemple.yaml "…"

# Veure la configuració resolta
parafrasi-cat --info --rules exemple-lexic
```

També funciona amb `python -m parafrasi_cat` i llegint de l'entrada
estàndard (`echo "text" | parafrasi-cat`).

### Des de Python

```python
from parafrasi_cat import PipelineConfig, build_pipeline, paraphrase

result = paraphrase("Gairebé tothom ho sap.", PipelineConfig(rule_set="exemple-lexic"))
print(result.output_text)          # Quasi tothom ho sap.
print(result.explain())            # informe complet en català
for t in result.transformations:   # cada canvi, explicat
    print(t.rule_id, t.text_before, "→", t.text_after, t.semantic_risk, t.explanation)
```

Vegeu [`examples/exemple_basic.py`](examples/exemple_basic.py).

## Arquitectura

```
text ─► analyzer ─► protected ─► rules ─► candidates ─► validation ─► scoring ─► pipeline ─► resultat
        (frases,    (fragments   (propostes  (identitat +  (invariants   (puntuació   (reconstrucció
         tokens)     intocables)  explicades)  variants)     de contingut)  i selecció)  del document)
```

| Paquet (`src/parafrasi_cat/`) | Responsabilitat |
|---|---|
| `core/` | Tipus compartits: `Span`, `Transformation`, `SemanticRisk`, errors, utilitats de text. |
| `analyzer/` | Segmentació en frases i tokenització basades en regles, amb offsets exactes. Protocol `Analyzer` per a adaptadors externs. |
| `morphology/` | `MorphFeatures`, `LexicalEntry`, `DictionaryMorphology`. Protocol `MorphologyProvider`. |
| `protected/` | `ProtectedSpan` i detectors de dates, xifres, números romans, cometes, citacions, noms propis i termes d'usuari. |
| `rules/` | Classe base `Rule`, `RuleContext`, regla de substitució lèxica, registre de tipus i conjunts de regles YAML. |
| `candidates/` | `Candidate` i `CandidateGenerator` (identitat + variants + combinacions compatibles). |
| `validation/` | Validadors d'invariants: fragments protegits, xifres, negació, modalitat, longitud. |
| `style/` | Perfils d'estil YAML, mètriques estilomètriques, distància d'estil, estimació a partir del corpus de l'autor. |
| `scoring/` | Pesos configurables, puntuació composta i selecció determinista. |
| `pipeline/` | `PipelineConfig`, `build_pipeline`, `Pipeline.run`, `ParaphraseResult` amb `explain()` i `to_json()`. |
| `resources.py` | Localització dels directoris de dades i lectura tipada de YAML/JSON. |
| `cli.py` | Interfície de línia d'ordres. |

Detalls a [`docs/arquitectura.md`](docs/arquitectura.md).

### La transformació com a unitat explicable

```python
Transformation(
    rule_id="lexical.substitution",
    text_before="Gairebé",
    text_after="Quasi",
    changed_span=Span(0, 7),                 # posició dins de la frase d'origen
    transformation_type=TransformationType.LEXICAL,
    confidence=0.9,                          # 0-1
    semantic_risk=SemanticRisk.LOW,          # none | low | medium | high
    explanation="S'ha substituït «Gairebé» per «Quasi», una forma equivalent…",
    metadata={"dictionary": "substitucions_lexiques.yaml"},
)
```

### Els fragments protegits

```python
ProtectedSpan(
    span=Span(3, 22),
    text="12 de gener de 2020",
    kind=ProtectionKind.DATE,   # proper_noun | date | number | roman_numeral | citation | quoted_text | user_term
    detector_id="date.regex",
)
```

Cap regla pot proposar un canvi que toqui un fragment protegit; si ho fa,
la canonada el descarta i ho explica. Després, els validadors comproven que
cada candidat conserva tots els fragments protegits i tots els invariants.

## Estructura del repositori

```
parafrasi-cat/
├── src/parafrasi_cat/        # codi del motor (vegeu la taula anterior)
├── resources/
│   ├── ca/
│   │   ├── lexicon/          # abreviatures, marcadors de modalitat i negació, sinònims (format)
│   │   ├── connectors/       # inventari de connectors per funció i registre
│   │   ├── transformations/  # diccionaris de substitució (dades de les regles)
│   │   └── morphology/       # formes flexionades (mostra) i format
│   └── style/                # perfils d'estil (default, formal)
├── dictionaries/             # termes protegits i noms propis de l'usuari
├── corpus/
│   ├── author/               # textos de l'autor (privats, no versionats)
│   ├── validation/           # frases de prova per als tests d'invariants
│   └── excluded/             # material exclòs (no versionat)
├── rules/                    # conjunts de regles (default = cap regla; exemple-lexic)
├── tests/                    # tests automatitzats (pytest)
├── examples/                 # exemple d'API, text i configuració
├── docs/                     # arquitectura, principis, formats, eines opcionals, full de ruta
├── pyproject.toml
└── README.md
```

## Configuració

Tot és editable en YAML o JSON:

- **Conjunts de regles** (`rules/*.yaml`): quines regles s'activen, risc
  màxim, confiança mínima. `default.yaml` no activa cap regla.
- **Perfils d'estil** (`resources/style/*.yaml`): longitud de frase objectiu,
  connectors preferits, mots a evitar.
- **Diccionaris de substitució** (`resources/ca/transformations/*.yaml`):
  equivalències amb risc i confiança per entrada.
- **Marcadors** (`resources/ca/lexicon/modalitat.yaml`): negació, atenuació,
  certesa.
- **Configuració de la canonada** (`--config`): vegeu
  [`examples/config_exemple.yaml`](examples/config_exemple.yaml).

Formats detallats a [`docs/format-de-recursos.md`](docs/format-de-recursos.md).

## Desenvolupament

```bash
make test        # pytest
make lint        # ruff (estil i format)
make typecheck   # mypy en mode estricte
make check       # tot
```

Per afegir una regla nova: subclasse de `Rule`, registre a
`rules/registry.py`, activació en un conjunt de regles i tests que
demostrin que respecta els fragments protegits.

## Eines externes

El motor no en necessita cap. Apertium, FreeLing, LanguageTool o Stanza es
podrien integrar en fases posteriors només com a adaptadors opcionals,
locals i desactivats per defecte; les seves llicències i condicions estan
documentades a
[`docs/eines-externes-opcionals.md`](docs/eines-externes-opcionals.md).
No s'ha copiat codi de cap altre repositori.

## Full de ruta

[`docs/full-de-ruta.md`](docs/full-de-ruta.md): lèxic i connectors (fase 2),
sintaxi (fase 3), estil de l'autor (fase 4).

## Llicència

Pendent de definir pel propietari del projecte.
