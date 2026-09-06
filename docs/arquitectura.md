# Arquitectura

Aquest document descriu l'arquitectura interna de `parafrasi-cat` i el
contracte de cada component. El README conté la visió general; aquí hi ha
els detalls que necessita qui vulgui ampliar el motor.

## Flux de dades

```
text d'entrada
   │
   ▼
[analyzer]  segmentació en frases + tokenització (offsets exactes)
   │
   ▼
[protected] detecció de fragments intocables (dates, xifres, noms, cometes, citacions, termes)
   │
   ▼  per a cada frase
[rules]     cada regla activa proposa Transformation(s) explicables (patrons, diccionaris,
   │        connectors, morfologia verbal, nominalitzacions, blocs sintàctics amb parser fiable)
   │        ├─ filtre: toca un fragment protegit?      → descartada
   │        ├─ filtre: risc semàntic > màxim?           → descartada
   │        └─ filtre: confiança < mínima?              → descartada
   ▼
[candidates] candidat identitat + un candidat per transformació + combinacions compatibles
   │
   ▼
[validation] invariants de contingut (fragments protegits, xifres, negació, modalitat, longitud,
   │        matriu de transicions epistemològiques per categoria)
   │        └─ candidat que falla → rebutjat (mai no se selecciona)
   ▼
[scoring]   puntuació composta (guany per canvis segurs, conscient de la família; grau estructural
   │        i superficial; penalització de degradació i del ritme de les fusions − distància
   │        d'estil; bonus assertiu petit si l'opció és activa) i selecció determinista
   ▼
[pipeline]  fase de paràgraf: regles entre frases i, al nivell 5 del mode profund, cerca en feix
   │        d'arquitectures alternatives de paràgraf (paragraph_search) amb balanç de cobertura;
   │        recompte d'oportunitats per frase i per paràgraf
   ▼
[pipeline]  reconstrucció del document conservant espais i salts de línia
   │
   ▼
ParaphraseResult (text resultant + informe complet)
```

## Paquets

| Paquet | Responsabilitat | Classes principals |
|---|---|---|
| `core` | Tipus compartits sense dependències internes | `Span`, `Transformation`, `TransformationType`, `SemanticRisk`, errors |
| `analyzer` | Anàlisi superficial basada en regles | `Tokenizer`, `SentenceSplitter`, `RuleBasedAnalyzer`, protocol `Analyzer` |
| `morphology` | Lemes i trets flexius | `MorphFeatures`, `LexicalEntry`, `DictionaryMorphology`, protocol `MorphologyProvider` |
| `protected` | Fragments intocables | `ProtectedSpan`, `ProtectionKind`, detectors, `Protector` |
| `rules` | Regles que proposen transformacions | `Rule`, `RuleContext`, `LexicalSubstitutionRule`, `BlockMoveRule`, `RuleRegistry`, `RuleSetConfig` |
| `candidates` | Construcció de versions alternatives | `Candidate`, `CandidateGenerator`, `GenerationTrace` |
| `validation` | Invariants de contingut | `Validator`, `ValidationResult`, validadors concrets, `EpistemicCategory`, matriu `TRANSITIONS` |
| `style` | Estilometria i perfils | `StyleProfile`, `StyleMetrics`, `StyleEvaluator`, `estimate_profile`, `FusionRhythm`, `epistemic_profile`, `ConnectorRepetition` |
| `scoring` | Puntuació i selecció | `ScoringWeights`, `CompositeScorer`, `AssertiveEvaluator`, `select_best` |
| `pipeline` | Orquestració i configuració | `Pipeline`, `PipelineConfig`, `build_pipeline`, `ParaphraseResult`, `ParagraphBeam` |
| `resources` (mòdul) | Localització i lectura de YAML/JSON | `ProjectPaths`, `load_mapping`, accessors tipats |
| `cli` (mòdul) | Interfície de línia d'ordres | `main` |

Regla de dependències: cada paquet només importa dels que té per sota a la
taula (i `core` no importa de cap). Això evita cicles i permet substituir
components sense tocar la resta.

## Contractes

### `Transformation`

Un canvi localitzat sobre una frase. Camps:

| Camp | Tipus | Significat |
|---|---|---|
| `rule_id` | `str` | Regla que ha proposat el canvi |
| `text_before` | `str` | Fragment original exacte |
| `text_after` | `str` | Fragment de substitució |
| `changed_span` | `Span` | Posició de `text_before` dins de la frase d'origen |
| `transformation_type` | `TransformationType` | lexical, connector, syntactic, morphological, punctuation, sentence_split, sentence_merge, identity |
| `confidence` | `float` (0-1) | Confiança de la regla |
| `semantic_risk` | `SemanticRisk` | none, low, medium, high |
| `explanation` | `str` | Explicació en llenguatge natural |
| `metadata` | `Mapping[str, str]` | Dades addicionals (font, diccionari...) |

Invariants: `changed_span.length == len(text_before)`; `apply(text)` només
funciona si `text[changed_span] == text_before`. Diverses transformacions
sobre la mateixa frase s'apliquen de dreta a esquerra i no poden solapar-se.

### `ProtectedSpan`

| Camp | Tipus | Significat |
|---|---|---|
| `span` | `Span` | Posició (relativa al text on s'ha detectat) |
| `text` | `str` | Contingut exacte |
| `kind` | `ProtectionKind` | proper_noun, date, number, roman_numeral, citation, quoted_text, user_term |
| `detector_id` | `str` | Detector que l'ha trobat |
| `note` | `str` | Informació opcional (p. ex. el terme d'usuari coincident) |

Els detectors treballen sobre el document sencer; `Protector.within` retalla
i desplaça els fragments perquè siguin relatius a cada frase.

### `Rule`

```python
class Rule(ABC):
    rule_id: str
    transformation_type: TransformationType
    description: str
    def propose(self, ctx: RuleContext) -> Iterable[Transformation]: ...
```

`RuleContext` ofereix la frase (tokens inclosos), els fragments protegits
relatius a la frase, el text del document, el perfil d'estil i el proveïdor
morfològic. Una regla **proposa**; mai no aplica. La canonada descarta
qualsevol proposta que toqui un fragment protegit, encara que la regla no ho
hagi comprovat.

Per afegir un tipus de regla:

1. Implementar una subclasse de `Rule` (p. ex. a `rules/`).
2. Registrar-la a `rules/registry.py` (`default_registry`) amb una fàbrica
   `(rule_id, params, paths) -> Rule`.
3. Activar-la en un conjunt de regles (`rules/<nom>.yaml`).
4. Afegir tests que demostrin que respecta els fragments protegits.

### `Validator`

```python
class Validator(Protocol):
    validator_id: str
    def validate(self, candidate: Candidate, ctx: ValidationContext) -> ValidationResult: ...
```

Un `ValidationResult` amb algun problema de severitat `error` fa que el
candidat quedi rebutjat i no arribi mai a la puntuació. Els validadors són
independents de les regles: són la segona línia de defensa del principi
fonamental.

Validadors de la fase 1:

| Identificador | Invariant |
|---|---|
| `protected_spans` | Cada fragment protegit apareix al candidat tantes vegades com a l'original |
| `numeric_invariants` | Multiconjunt de xifres i de números romans idèntic |
| `negation` | Recompte de marcadors de negació idèntic (amb excepcions com «no obstant això») |
| `modality` | Els atenuadors no disminueixen; els marcadors de certesa no augmenten |
| `length_ratio` | Longitud dins d'un marge respecte de l'original |

### `Scorer`

`CompositeScorer.score(candidate)` retorna un `ScoreBreakdown` amb el total
i els components:

- `transformacions`: `Σ confiança × (1 − pes_risc × risc) / max_transformations`
- `estil`: `− pes_estil × distància(candidat, perfil)`

El candidat identitat sempre té guany 0, de manera que només es prefereix
un canvi si és segur. `select_best` desempata a favor del candidat amb menys
transformacions i, després, del primer.

### `Analyzer` i adaptadors externs

`Analyzer.analyze(text) -> Analysis` és l'únic punt de contacte amb
l'anàlisi lingüística. Un adaptador d'una eina externa (Apertium, FreeLing,
LanguageTool, Stanza...) ha de produir el mateix `Analysis` (frases amb
offsets exactes i tokens amb offsets relatius a la frase). Vegeu
`docs/eines-externes-opcionals.md` abans d'integrar-ne cap.

## Localització de recursos

`resources.ProjectPaths.discover()` cerca el directori arrel en aquest ordre:
paràmetre `home` → variable `PARAFRASI_CAT_HOME` → clon del repositori
(cercant `resources/ca` cap amunt des del paquet) → dades empaquetades
(`parafrasi_cat/_data`, generades en construir la roda).

## Determinisme

Tot el motor és determinista: no hi ha aleatorietat, ni models, ni crides
externes. Amb la mateixa entrada, la mateixa configuració i els mateixos
recursos, el resultat és sempre idèntic. Els tests ho comproven.
