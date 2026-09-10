# Fiabilitat del motor i de l'empremta

Aquest document recull dues comprovacions acotades: si les regles sintàctiques
afegides fa poc **generalitzen** més enllà dels exemples que les van motivar, i
què es pot saber d'una empremta d'autor **mirant-la**.

## 1. Bateria de vint frases noves

`tests/test_bateria_sintactica.py` passa pel motor vint frases que no són cap de
les que van motivar les regles, amb vocabulari i construccions diferents, i amb
el **parser local real**: si no hi ha model instal·lat, els tests s'ometen i s'hi
diu. Els tests d'arbre construït a mà són en un altre fitxer
(`tests/test_blocs_reflexius.py`) i no es barregen amb aquests.

| Grup | Frases | Què s'hi prova |
| --- | --- | --- |
| A | 5 | Presentatius amb identificació darrere dels dos punts |
| B | 5 | Incisos amb verbs pronominals o reflexius |
| C | 5 | Subordinades coordinades |
| D | 5 | Casos ambigus que el motor s'ha d'estar de tocar |

De cada frase se'n declara **què s'hi admet** (una alternativa estructural, o
abstenció) i **què no hi pot canviar mai**. Els invariants valen per a totes les
frases i es comproven a *tots* els candidats, no només al preferit: un candidat
dolent que no guanyi continua sent un candidat dolent.

| Invariant | Com es comprova |
| --- | --- |
| Negació | Mateix recompte de `no, ni, cap, mai, tampoc, gens, ningú, res, enlloc` |
| Modalitat | Mateix recompte de `sembla, pot, cal, potser, deu…` i de la perífrasi d'obligació |
| Xifres i nombres romans | Mateix recompte, tal com són; no s'hi normalitza res |
| Noms propis | Mateixos mots en majúscula que no obren la frase |
| Abast dels quantificadors | Cap universal (`tots`, `cada`, `qualsevol`, `sempre`) que la frase no tingués |
| Identitat | Cap còpula nova si els dos punts no identificaven res |

No s'hi exigeix cap redacció literal: la prova és l'invariant, no la frase.

### Resultat

Vint frases triades. **No és cap percentatge de millora general**, i no es pot
extrapolar a cap text.

| | |
| --- | --- |
| Amb almenys una alternativa estructural correcta | **15** |
| Només amb variants de superfície | **2** |
| Abstencions completes | **3** |
| Transformacions incorrectes | **0** |

Les cinc abstencions o variants de superfície són els cinc casos del grup D, tots
justificats i amb l'evidència de l'arbre al fitxer de test.

### Errors concrets que va destapar

**Nombre comparat entre categories diferents.** El criteri de confiança comparava
el nombre del parser amb el del recurs morfològic local sense mirar de quina
categoria parlava cadascú. El conjecturador llegeix «arxiu» com si fos una segona
persona del plural del verb «arxir» (`pl`); el parser hi veu un nom singular, i
«L'arxiu, quan es va constituir al segle XVI, no tenia cap inventari» quedava
degradada al nivell 2. Ara `numbers_of` rep també la categoria del parser i només
compara lectures de la mateixa categoria (`COMPARABLE_POS`, a
`syntax/spacy_parser.py`). La comprovació entre noms, que és per a la qual
serveix, no s'ha tocat.

**L'article elidit llegit com una sigla.** El filtre `lower` respectava qualsevol
mot inicial en majúscules de més d'un caràcter per no espatllar «UE» o «XVI».
«L'» té dos caràcters i una sola lletra, i sortia «Quan es va constituir al segle
XVI, L'arxiu no tenia cap inventari». Ara es compten les lletres.

**Dos subjectes per a un verb.** A «Hi ha una condició que cal complir: no
arribar tard», l'analitzador marca «que» com a `nsubj` de «cal» i alhora
«complir» com a `csubj`. La regla es refiava del primer i proposava «Una condició
cal complir», que no vol dir el mateix. `relative_subject_of` demana ara que el
verb no tingui cap altre subjecte: un arbre que se'n contradiu no autoritza a
reescriure res.

**Locucions esborrades de les propostes de sinònims.** La passada de
concordança del suggeridor treia de la llista qualsevol proposta que encavalqués
un nom, per no deixar substituir mai un nom sense la seva concordança. El «causa»
de «a causa de» és un nom per a l'analitzador —i no és cap nom substituïble: és
un tros d'una preposició—, de manera que «a causa de → per raó de» desapareixia
sense que res la substituís. Ara els noms d'una locució (relacions `fixed` i
`flat`) no compten. El defecte hi era d'abans; només es veia amb l'anàlisi
fiable, i la correcció anterior el va fer visible.

### Cas que continua sent ambigu

A «Hi ha un llibre que val la pena llegir» l'analitzador marca «que» com a
subjecte de «val» de manera internament coherent —no hi ha cap segon subjecte—, i
la regla hi actua. No s'hi ha programat cap excepció: fer-ho seria una llista de
verbs, no una regla.

## 2. Què es pot saber d'una empremta

### El corpus

Dos fitxers amb el mateix contingut compten una sola vegada, encara que tinguin
noms diferents. La comparació es fa sobre el text normalitzat **només en allò que
no en canvia res**: final de línia, espai al final de cada línia i línies en blanc
als extrems. La puntuació, les majúscules i els espais interiors es conserven:
dos textos que hi difereixin són documents diferents. Es conserva el primer per
ordre de nom i la resta queda a `Corpus.excluded` amb el nom del document del
qual és còpia.

Un document que és al corpus principal i al de validació es conserva **al
principal** i s'exclou del de validació. Si no, l'empremta es compararia amb un
text que ella mateixa ha ajudat a definir i la validació sortiria bona per
construcció.

Cap fitxer original no es toca: excloure és no llegir-lo, no esborrar-lo. Tampoc
no s'hi dedueix autoria ni procedència amb cap detector: només es comparen
continguts.

### L'informe

`style build` i `style show` fan servir el mateix informe
(`parafrasi_cat.style.report`):

```
Empremta «autor» (esquema 1.1)
  mena de corpus: prosa d'investigació
  documents: 12 · paràgrafs: 84 · frases: 310 · paraules: 9 412
  textos exclosos: 3 (2 per contingut repetit)
    · copia-final.md: duplicat de «capitol-3.md» (mateix contingut)
    · validation/capitol-3.md: ja és al corpus principal com a «capitol-3.md»: …
  model sintàctic: spaCy ca_core_news_md-3.8.0 (només analitza; no genera res)
  frases analitzades: 298 · descartades per anàlisi poc fiable: 12 · confiança high
  confiança per component (indicador intern derivat d'observacions i documents,
  no cap probabilitat estadística):
    longitud de frase 0.91 · comes 0.94 · connectors 0.78 …
  contingut: 34 característiques numèriques i 68 fragments literals del corpus
  validació independent: 3 documents, 62 frases, distància 0.214 (confiança high)
    el text reservat coincideix amb l'empremta
```

**Fragments d'exemple.** L'empremta desa **fragments literals curts del corpus**
—fins a tres per tret, retallats a 110 caràcters per defecte— per il·lustrar cada
connector, cada expressió recurrent i cada variant preferida. No és només un
recompte, i l'informe en diu el nombre exacte. Els límits són a
`resources/ca/style/estilometria.yaml` (`examples_per_feature`,
`example_max_chars`).

**Confiança.** És un indicador intern derivat del nombre d'observacions i de
documents, no cap probabilitat estadística demostrada. L'informe ho diu cada
vegada que en mostra una.

**Validació.** Distingeix tres coses que és fàcil confondre:

| Veredicte | Què vol dir |
| --- | --- |
| *sense validació independent* | No s'ha reservat cap text: no s'ha comprovat res |
| *sense dades suficients* | Hi ha text reservat, però massa poc: la distància no decideix res |
| *el text reservat coincideix* | Hi ha prou text i s'assembla a l'empremta |
| *estil poc coincident* | Hi ha prou text i s'aparta de l'empremta |

El llindar de «prou text» és el mateix criteri que la resta del perfil
(`confidence_level`: 40 frases i 2 documents per a `high`, 15 frases per a
`medium`). El veredicte queda desat a `validation.verdict`; a les empremtes
anteriors es dedueix dels recomptes que ja hi eren.

### Què no fa l'empremta

L'empremta orienta la tria **entre candidats que ja són segurs**. No autoritza
cap transformació que el motor no autoritzaria sense ella, i mai no canvia el que
una frase afirma ni la seguretat amb què ho afirma per assemblar-se més a
l'autor.

## Com regenerar i comprovar la vostra empremta

```bash
# 1. Reconstruir-la, amb textos reservats per validar-la i una etiqueta de corpus
parafrasi-cat style build corpus/autor/ \
    --validation corpus/autor-validacio/ \
    --corpus-type "prosa d'investigació"

# 2. Tornar-la a llegir quan calgui
parafrasi-cat style show style/autor.json

# 3. Comparar-la amb una versió anterior
parafrasi-cat style compare style/autor.json style/autor-anterior.json
```

Què mirar de l'informe, per ordre:

1. **Textos exclosos.** Si hi apareix cap duplicat que no esperàveu, mireu si
   teniu el mateix text dues vegades al directori.
2. **Frases descartades.** Moltes frases descartades vol dir que el parser no se
   n'acaba de sortir amb aquell text; l'empremta continua sent vàlida, però el
   perfil sintàctic hi pesa menys.
3. **Confiança per component.** Un component amb «sense dades» no és un error:
   vol dir que el corpus no en té prou exemples.
4. **Validació.** Si diu «sense dades suficients», reserveu-hi més text; si diu
   «estil poc coincident», mireu si els textos reservats són realment del mateix
   registre.
