# parafrasi-cat

Motor **local** de reredacció i parafraseig en català, amb una interfície web
que s'executa al mateix ordinador.

> **El motor no utilitza LLM ni serveis generatius. La reredacció es produeix
> mitjançant regles lingüístiques explícites, recursos editables, anàlisi
> estilomètrica i selecció determinista de candidats.**

**Estat: versió funcional.** Hi ha 40 regles declaratives repartides en 13
famílies, protecció de contingut, validació semàntica i epistemològica,
puntuació multidimensional, diccionaris per projecte, preferències d'autor,
feedback manual i una interfície local. Amb la mateixa entrada i la mateixa
configuració, el resultat és sempre idèntic.

## Què és

- Un motor que **proposa variants** d'un text en català i n'explica cadascuna:
  quina regla l'ha generada, quin risc té i per què s'ha triat o descartat.
- Una eina **assistida**: mostra els candidats perquè una persona en triï un,
  l'editi i el validi.
- Un projecte de **recursos editables**: les regles, els diccionaris, les
  preferències i el feedback són fitxers YAML que podeu llegir, modificar i
  versionar amb Git.

## Què no és

- **No és un LLM ni una API generativa.** No hi ha cap model neuronal, cap
  crida a cap servei i cap dependència que en necessiti.
- **No és un reescriptor autònom.** El resultat s'ha de revisar: el motor
  garanteix que no altera dades, no que la frase resultant sigui sempre la
  millor opció estilística.
- **No inventa contingut.** No afegeix informació, no treu matisos i no
  resumeix.
- **No aprèn.** El feedback són recomptes explícits en un YAML, no un model
  entrenat.
- **No envia res enlloc.** No hi ha telemetria ni connexions de sortida.

## Principi fonamental

**El contingut original és intocable.** El motor pot canviar la *forma* d'una
frase, però no pot alterar noms propis, dates, xifres, números romans,
citacions, text entre cometes, terminologia protegida, negacions ni la força
epistemològica. Cada prohibició té un mecanisme concret: detectors de
fragments protegits abans d'aplicar cap regla, i validadors que tornen a
comprovar cada candidat. Un candidat que en trenqui cap queda invalidat i mai
no se selecciona.

Vegeu [`docs/principis-de-preservacio.md`](docs/principis-de-preservacio.md).

## Garanties

| Garantia | Com es compleix |
|---|---|
| Cap LLM ni model generatiu | Només regles, diccionaris i heurístiques deterministes. Un test comprova que el paquet no importa cap biblioteca de models. |
| Cap connexió de sortida | L'únic paquet extern és PyYAML. Un test comprova que cap fitxer del paquet importa un client de xarxa, ni tan sols el servidor local. |
| Cap telemetria | El registre de traçabilitat és local, opcional i desactivat per defecte. |
| Explicabilitat | Cada transformació porta explicació, regla, risc i confiança; la interfície i `--explain` les mostren. |
| Determinisme | Mateixa entrada i mateixa configuració donen sempre el mateix resultat. |

## Instal·lació

Requereix Python 3.11 o superior.

```bash
git clone <url-del-repositori> parafrasi-cat
cd parafrasi-cat
pip install -e ".[dev]"
```

## Interfície local

```bash
parafrasi-cat web                       # obre http://127.0.0.1:8765/
parafrasi-cat web --port 9000 --no-browser
parafrasi-cat web --enable-history      # arrenca amb el registre actiu
```

El servidor es lliga a l'amfitrió local i la pàgina no carrega cap recurs
extern. Des de la interfície podeu:

- escriure o enganxar el text;
- triar **nivell** (1-5), **empremta o perfil d'estil**, un o diversos
  **diccionaris**, un fitxer de **preferències** i el **mode**;
- generar candidats i veure, per a cada frase o paràgraf, el text original, el
  millor candidat i la resta de candidats;
- veure, de cada candidat, les **diferències** respecte de l'original, les
  **regles aplicades**, les **puntuacions** per dimensió i els **advertiments**
  de validació, amb el motiu del descart si no s'ha acceptat;
- consultar els **fragments protegits** que s'han detectat;
- marcar un candidat com a **preferit**, **acceptable** o **rebutjat**;
- **editar** el resultat final a mà, **copiar-lo** o **exportar-lo**.

## Ús per CLI

```bash
# Reescriptura amb informe de candidats, puntuacions i descartats
parafrasi-cat rewrite text.txt --level 3
parafrasi-cat rewrite text.txt --style style/author.json \
  --dictionary dictionaries/historia.yml --preferences preferences/author.yml
parafrasi-cat rewrite text.txt --max-risk low --min-confidence 0.75 --quiet

# Reescriptura curta, amb explicació o en JSON
parafrasi-cat --rules parafrasi --explain "Gairebé sempre plou, tot i que avui no."
parafrasi-cat --rules parafrasi --json --input text.txt

# Terminologia protegida des de la línia d'ordres
parafrasi-cat --rules parafrasi --protect "capital circulant" --protect-file termes.txt "…"

# Empremtes estilístiques i feedback
parafrasi-cat style build corpus/author/ --profile resources/style/autor.yaml
parafrasi-cat feedback preferred "obra de"
parafrasi-cat feedback show

# Configuració resolta i fitxer de configuració
parafrasi-cat --info --rules parafrasi
parafrasi-cat --config examples/config_exemple.yaml "…"
```

També funciona amb `python -m parafrasi_cat` i llegint de l'entrada estàndard.

### Des de Python

```python
from parafrasi_cat import PipelineConfig, build_pipeline

config = PipelineConfig(rule_set="parafrasi", level=3, dictionaries=("historia",))
result = build_pipeline(config).run("Van trobar un fèretre de pedra a la cripta.")
print(result.output_text)          # Trobaren un sarcòfag de pedra a la cripta.
print(result.report())             # candidats, puntuacions i descartats
for t in result.transformations:
    print(t.rule_id, t.text_before, t.text_after, t.semantic_risk, t.explanation)
```

## Nivells 1-5

El nivell limita fins on poden arribar les regles. Un nivell més alt
n'habilita més, però no relaxa cap protecció.

| Nivell | Abast | Regles actuals |
|---|---|---|
| 1 | Lèxic: substitucions de paraules i locucions | 3 |
| 2 | Connectors equivalents dins la mateixa funció discursiva | 7 |
| 3 | Sintaxi: còpula, agent, presència, ordre, temporals, subordinades | 26 |
| 4 | Entre frases: fusió, divisió i puntuació | 4 |
| 5 | Paràgraf | cap encara |

El nivell 5 està reservat per a regles de paràgraf que encara no existeixen:
avui, triar 5 dona el mateix resultat que triar 4.

## Modes

Un mode és un envoltant de seguretat sobre la configuració. **Cap dels dos
modes no toca les proteccions**: els termes protegits, els diccionaris, les
preferències i la llista de validadors són idèntics en tots dos, i un test ho
comprova.

| | Conservador | Reredacció profunda |
|---|---|---|
| Risc semàntic màxim | baix | mitjà |
| Confiança mínima | 0,75 | la del conjunt de regles (0,55) |
| Transformacions per candidat | 1 | fins a 3 |
| Reaplicació de regles | no | sí |
| Nivell màxim | 3 | 5 |
| Marge de longitud | 0,8-1,25 | 0,6-1,6 |

El **mode conservador** només accepta canvis de risc baix i confiança alta,
no en combina cap i no reestructura entre frases. Si cap alternativa no és
clarament segura, la puntuació deixa guanyar el text original.

El **mode profund** arriba fins al nivell 5, combina transformacions i
reaplica regles sobre els millors candidats. El que **no** pot fer, en cap
cas, és alterar noms propis, dates, xifres, números romans, citacions, text
protegit, terminologia protegida, negacions ni força epistemològica.

Els modes són un concepte de la interfície. Des del CLI s'obté l'equivalent
amb `--level`, `--max-risk` i `--min-confidence`.

## Corpus

```
corpus/
├── author/       # els vostres textos, per construir l'empremta (no es versiona)
├── excluded/     # material que no ha d'entrar a l'anàlisi (no es versiona)
├── exemples/     # tres estils d'exemple (academic, concis, narratiu) amb validació
└── validation/   # frases de prova del motor
```

`corpus/author/` i `corpus/excluded/` estan al `.gitignore`: els textos
privats no es publiquen mai.

## Empremta estilística

L'anàlisi del corpus d'un autor produeix una empremta JSON explícita i
editable (`style/<autor>.json`): longitud de frase, connectors, densitat de
puntuació, variants equivalents preferides i altres característiques, cadascuna
amb el nombre d'observacions, la confiança i la variabilitat.

```bash
parafrasi-cat style build corpus/author/ --validation corpus/validacio/
parafrasi-cat style compare style/author.json style/altre.json
parafrasi-cat style show style/author.json
```

L'empremta es calcula amb recomptes i estadístics robustos, no amb cap model.
El repositori no en porta cap: es genera a partir del vostre corpus. Fins
llavors, la interfície ofereix els perfils de `resources/style/`.

## Diccionaris

Diccionaris terminològics per projecte, a `dictionaries/*.yml`, que s'activen
sols o combinats.

```yaml
entries:
  - term: sarcòfag
    preferred: [sarcòfag]
    accepted: [sarcòfag funerari]
    avoid: [fèretre]
    protected: true
    pos: nom
    notes: "No substituir en contextos arqueològics."
```

- `protected`: el terme i les seves formes preferides i acceptades passen a
  ser fragments protegits. **Cap regla estilística no pot sobreescriure un
  terme protegit.**
- `avoid` a `preferred`: es proposa la substitució i es penalitza qualsevol
  candidat que introdueixi una forma a evitar.
- `accepted`: neutres.

Amb diversos diccionaris actius, la protecció és acumulativa i, si dos
diccionaris discrepen sobre una forma, mana el primer de la llista.

Detalls a [`dictionaries/README.md`](dictionaries/README.md).

## Preferències

`preferences/author.yml` recull les preferències explícites de l'autor:

```yaml
prefer: ["així com", "per tant"]
avoid: ["a nivell de", "en base a"]
preferred_connectors: [tanmateix, "així doncs"]
preferred_sentence_length: 22
max_sentence_length: 45
preferred_variants:
  "obra de": 1.0
  "fet per": 0.4
  "realitzat per": 0.7
```

### Jerarquia de prioritats

1. fragments protegits explícitament;
2. termes protegits dels diccionaris;
3. formes preferides, acceptades o a evitar dels diccionaris;
4. preferències explícites de l'autor i, després, el feedback;
5. empremta estadística;
6. preferències generals del motor.

Una forma amb preferència explícita (nivells 1-4) no es torna a valorar amb
l'empremta estadística.

## Feedback

L'autor pot marcar una variant com a **preferida**, **acceptable** o
**rebutjada**, des de la interfície o des del CLI. Els recomptes es desen en
un YAML llegible:

```yaml
prior: 3
variants:
  obra de: {preferred: 4, acceptable: 2, rejected: 0}
  fet per: {preferred: 0, acceptable: 1, rejected: 3}
```

El pes d'una variant és la mitjana d'aprovació suavitzada amb `prior`
observacions neutres: `(preferred + 0,5·acceptable + 0,5·prior) / (total +
prior)`. Amb `prior` 3, una sola decisió mou el pes de 0,50 a 0,625, de manera
que cap tria aïllada no capgira les preferències. No s'hi entrena res: el pes
es recalcula cada vegada a partir d'uns nombres que qualsevol pot llegir i
editar.

La decisió del selector és explicable: l'informe diu, per exemple, que un
candidat guanya perquè introdueix «obra de», que l'autor ha marcat com a
preferida 4 vegades, i elimina «fet per», rebutjada 3 vegades.

Detalls a [`preferences/README.md`](preferences/README.md).

## Protecció epistemològica

Cada expressió del lèxic epistemològic
(`resources/ca/lexicon/epistemologia.yaml`) té una **funció** (dubte,
possibilitat, aparença, indici, demostració) i una **força** (0 a 4). El
validador bloqueja qualsevol candidat que canviï el perfil epistemològic de
la frase, si la regla que el proposa no hi està autoritzada explícitament.

Dues classes de la mateixa força no són equivalents: «indica» no és
«suggereix» i «demostra» no és «confirma». Una hipòtesi no pot esdevenir una
afirmació, ni al mode profund. Per exemple, «Aquesta documentació permet
plantejar que l'església podria haver existit abans del 1050, però no es pot
demostrar» es pot dividir en dues frases, però cap candidat acceptat no en
treu «podria» ni el converteix en una certesa.

## Traçabilitat

El registre local és **opcional i està desactivat per defecte**. Quan està
desactivat no s'escriu res: ni el text, ni la configuració, ni cap metadada.

Quan s'activa, cada reescriptura desa una línia JSON a
`history/parafrasi-cat.jsonl` amb el text original, la data, la configuració,
l'empremta, els diccionaris, les preferències, el nivell, els candidats amb
les puntuacions, el candidat seleccionat, les regles aplicades, el feedback i
l'edició manual final. El fitxer és local, llegible, exportable des de la
interfície i està al `.gitignore`.

## Com afegir una regla

Les regles es declaren com a dades, no com a codi:

1. Afegiu la definició a `resources/ca/transformations/<família>.yaml` amb
   `rule_id`, `engine`, `category`, `level`, `semantic_risk`, `confidence`,
   `pattern`, `transformation`, `conditions`, `exceptions` i **exemples
   positius i negatius**.
2. Si és una família nova, incloeu el fitxer a `rules/parafrasi.yaml`.
3. Afegiu el `rule_id` a `RULE_IDS`, a
   `tests/test_regles_definicions.py`: el test comprova que la regla compleix
   tots els seus exemples i que té les metadades completes.
4. Executeu `make check`.

Per a un motor nou (no un patró de tokens), implementeu una subclasse de
`Rule` i registreu-la a `rules/registry.py`.

El format del motor de patrons és a
[`docs/format-de-recursos.md`](docs/format-de-recursos.md) i el contracte de
cada component, a [`docs/arquitectura.md`](docs/arquitectura.md).

## Arquitectura

```
text ─► analyzer ─► protected ─► rules ─► candidates ─► validation ─► scoring ─► pipeline ─► resultat
        (frases,    (fragments   (propostes  (identitat +  (invariants   (puntuació   (reconstrucció
         tokens)     intocables)  explicades)  variants)     i epistemo-   i selecció)  del document)
                                                             logia)
```

| Paquet (`src/parafrasi_cat/`) | Responsabilitat |
|---|---|
| `core/` | `Span`, `Transformation`, `SemanticRisk`, errors, utilitats de text. |
| `analyzer/` | Frases, tokens, clítics, apòstrofs, numerals i lexicó de classes tancades. |
| `morphology/` | Trets flexius interns i adaptadors opcionals (Apertium, FreeLing). |
| `protected/` | Detectors de dates, xifres, romans, cometes, citacions, noms propis i termes. |
| `rules/` | Motor de patrons, regles declaratives, registre de motors i conjunts de regles. |
| `candidates/` | `Candidate` i generació de variants, combinacions i reaplicacions. |
| `validation/` | Invariants de contingut, terminologia, epistemologia i gramaticalitat. |
| `style/` | Perfils, mètriques, empremta estilística i preferències derivades. |
| `dictionaries/` | Diccionaris terminològics per projecte. |
| `preferences/` | Preferències explícites, feedback i jerarquia de prioritats. |
| `scoring/` | Pesos, puntuació multidimensional i selecció determinista. |
| `pipeline/` | Configuració, modes, construcció de la canonada i resultats. |
| `web/` | Servei, servidor local i pàgina de la interfície. |
| `cli.py` | Línia d'ordres i subordres. |

## Desenvolupament

```bash
make test        # pytest
make lint        # ruff (estil i format)
make typecheck   # mypy en mode estricte
make check       # tot
```

## Límits coneguts

Perquè quedi clar què es pot esperar del motor:

- **No hi ha analitzador morfosintàctic.** Els límits dels sintagmes es
  dedueixen amb heurístiques i un lexicó de classes tancades. En català hi ha
  molta homografia entre noms i verbs, i és on es concentren els errors.
- **La gramaticalitat de la sortida no es comprova a fons.** El validador
  detecta contraccions incorrectes, signes desaparellats i defectes de
  puntuació, però no concordança ni règim verbal.
- **La cobertura és limitada.** Amb 40 regles, moltes frases no encaixen amb
  cap i es retornen sense canvis.
- **Les regles s'han desenvolupat sobre un corpus petit.** El rendiment sobre
  text arbitrari serà inferior al dels exemples del repositori.

Les proteccions de contingut, en canvi, són estructurals i es comproven a
cada candidat.

## Eines externes

El motor no en necessita cap. Apertium i FreeLing es poden integrar com a
adaptadors opcionals, locals i desactivats per defecte; les seves llicències
estan documentades a
[`docs/eines-externes-opcionals.md`](docs/eines-externes-opcionals.md).
No s'ha copiat codi de cap altre repositori.

## Llicència

Pendent de definir pel propietari del projecte.
