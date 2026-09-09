# Cobertura sintàctica: dos punts, presentatius i selecció

Abast d'aquesta entrega: quatre problemes concrets observats en una mostra
petita. No és una auditoria del motor ni s'hi promet cap percentatge de millora
general: la mostra és massa petita per sostenir-lo.

Reproducció de tot el que hi ha aquí:

```
python scripts/install_parser.py --yes --model ca_core_news_md
python -m pytest tests/test_dospunts_presentatius.py tests/test_nivell5_focalitzat.py -q
```

## 1. Per què «reina» bloquejava la frase al nivell 2

La frase

> La reina, quan apareix o quan es consolida, tampoc no necessita una explicació
> excessiva: ocupa el lloc immediat del poder domèstic, dinàstic i polític al
> costat del rei.

quedava limitada al nivell 2 amb la nota «el nucli "reina" no és un verb ni un
predicat amb còpula».

**L'error és del model, no de l'adaptador ni de la interpretació de
dependències.** Passant la frase directament a spaCy, sense cap codi del
projecte pel mig, `ca_core_news_sm` etiqueta `reina` com a `PROPN` i com a
`ROOT`, penja `apareix` com a `acl` del nom i `necessita` com a `conj`
d'`apareix`. L'adaptador es limita a copiar aquest arbre, i
`assess_confidence` fa exactament el que ha de fer: veure que el nucli no és un
predicat i no autoritzar res d'estructural.

El desencadenant no és el nom ni la doble negació, sinó **l'incís temporal
coordinat**:

| Frase | Arrel amb `sm` | Arrel amb `md` |
|---|---|---|
| La reina, quan apareix, tampoc no necessita una explicació excessiva. | `necessita` | `necessita` |
| La reina tampoc no necessita una explicació excessiva. | `necessita` | `necessita` |
| La reina, quan apareix o quan es consolida, tampoc no necessita una explicació excessiva. | `reina` | `necessita` |
| El rei, quan apareix o quan es consolida, tampoc no necessita una explicació excessiva. | `rei` | `necessita` |
| El rei, quan apareix i quan es consolida, no necessita res. | `rei` | `rei` |

**La correcció aplicada** és triar un analitzador millor entrenat, no imposar
cap arrel: el motor fa servir el model català més exacte que trobi instal·lat
(`ca_core_news_lg` → `md` → `sm`), es pot fixar un model concret amb
`syntax: spacy:<model>` o amb la variable d'entorn `PARAFRASI_SPACY_MODEL`, i
`scripts/install_parser.py` accepta `--model`. Els tres models tenen el mateix
esquema d'etiquetes i la mateixa llicència, i el criteri de confiança continua
rebutjant igualment les anàlisis incoherents.

**El que continua bloquejat.** Amb `md`, la frase de la reina ja arriba al
nivell 3, però la reordenació de l'incís no es proposa: el bloc
«quan apareix o quan es consolida» conté el pronom feble «es», i les guardes de
moviment de blocs el rebutgen (`no_clitic`, i el control d'anàfores en un
moviment cap al davant). És una guarda de seguretat existent; no s'ha tocat.
L'última fila de la taula mostra que la coordinació amb «i» continua mal
analitzada en tots dos models: aquí el bloqueig es manté i és correcte que s'hi
mantingui.

## 2. Patrons nous

### Dos punts explicatius

`dospunts.explicacio_a_relativa_del_subjecte` (nivell 3, família
`SUBORDINATION`, a `resources/ca/transformations/dos_punts.yaml`).

Els dos punts no diuen quina relació hi ha entre les dues parts: poden
introduir una explicació, una identificació, una enumeració, una conseqüència o
una citació. Per això la regla **no hi afegeix cap connector causal**. L'única
reformulació autoritzada conserva les dues proposicions i no canvia la força de
cap: quan el tros de darrere dels dos punts és una clàusula sense subjecte
propi, en present d'indicatiu i amb un verb que concorda amb el subjecte de la
principal, es pot dir com a relativa explicativa d'aquest subjecte.

```
El rei no necessita gaire justificació: és el centre del tauler i el centre del regne.
→ El rei, que és el centre del tauler i el centre del regne, no necessita gaire justificació.
```

No s'aplica a enumeracions ni identificacions (no hi ha clàusula), al passat ni
a les perífrasis (`va perdre`: l'auxiliar no és el verb de l'explicació), quan
l'explicació té subjecte propi, quan la concordança no quadra, ni quan entre el
subjecte i els dos punts ja hi ha un incís.

### Presentatius «hi ha … que …»

`presentatiu.hi_ha_np_relativa_a_subjecte` i
`presentatiu.hi_ha_plural_nu_a_quantificador` (nivell 3, família `SYNTACTIC`, a
`resources/ca/transformations/presencia.yaml`).

```
Però hi ha una peça que no encaixa tan fàcilment: l'orfil.
→ Però una peça no encaixa tan fàcilment: l'orfil.

Hi ha llibres que expliquen la història del joc.
→ Alguns llibres expliquen la història del joc.
```

La reescriptura toca només el tros «hi ha X que» i deixa la resta de la frase
intacta, de manera que la negació, els quantificadors i els matisos del
predicat no es poden perdre. Condicions: el presentatiu ha d'obrir la frase
(com a molt darrere d'una conjunció com «Però»), i l'analitzador ha de
confirmar que «que» és el **subjecte** relatiu d'un verb conjugat que concorda
amb el sintagma. Amb «que» com a complement («hi ha coses que no entenc»)
treure el presentatiu deixaria un sintagma sense oració, i no es proposa res.
Amb l'existencial negat o subordinat («no hi ha…», «si hi ha…») tampoc.

**Límit documentat.** Amb un plural sense determinant, la promoció a subjecte
exigeix un quantificador, i el quantificador ha de concordar en gènere. El
gènere només s'accepta si l'analitzador el dona o si el recurs morfològic el
dona amb confiança alta. La frase de prova

> Hi ha peces dels escacs que semblen haver conservat el seu nom perquè la seva
> funció era clara.

no obté aquesta alternativa: ni `ca_core_news_sm` ni `ca_core_news_md` marquen
el gènere de «peces», i l'endevinador morfològic intern hi respon amb confiança
0,2 —el mateix endevinador que classifica «homes», «pares» i «llibres» com a
femenins—. Amb aquesta evidència, escriure «algunes» seria endevinar. La regla
calla. Amb el recurs morfològic de Softcatalà instal·lat
(`scripts/install_morphology.py`) el gènere sí que hi és per a molts noms i la
regla s'hi aplica.

## 3. Selecció i puntuacions

### Què és `qualitat_sintactica`

És `1 − degradació estructural local` (`parafrasi_cat.style.degradation`). Mesura
tres senyals comparant el candidat amb l'original: relatives consecutives amb
el mateix marcador, subordinants «que» de més i la mateixa estructura repetida
dins d'una frase. Que baixi d'1 a 0,8 vol dir «aquest candidat afegeix un
subordinant "que"». No és una nota de qualitat global ni un percentatge.

En el cas observat, `perquè` → `ja que` afegeix literalment un «que» i la
mètrica ho detecta bé. El problema era que el candidat guanyava igualment.

### Per què guanyava

Dues causes, totes dues corregides:

1. **El guany per transformacions es cobrava pel sol fet d'haver-hi un canvi.**
   La substitució rebia +0,15, molt per damunt de la penalització de −0,10 per
   degradació: el saldo era positiu i guanyava. Ara, un canvi que **no
   reorganitza** la frase i que a sobre **degrada** l'estructura local no cobra
   cap guany: amb la penalització, queda per sota de l'original. Un candidat
   estructural sí que en cobra, perquè allà la degradació és el preu d'una
   reestructuració real —i el component «estructura» ja la paga multiplicada per
   la qualitat sintàctica.
2. **La distància d'estil premiava allargar el connector.** Amb el perfil per
   defecte, la distància només depèn de la longitud mitjana de frase (objectiu:
   20 mots). «No obstant això, hi ha una peça…» és més llarga que «Però hi ha
   una peça…» i, per tant, més a prop de l'objectiu: guanyava per haver afegit
   mots. Ara la longitud només compta quan el candidat canvia **quantes frases
   hi ha** (una divisió o una fusió); mentre no en canviï cap, es pren de
   l'original i s'anul·la a la comparació. La resta de components de l'estil
   (mots evitats, connectors preferits, comes i variants de l'autor) continuen
   comptant igual.

### El que no s'ha fet, i per què

La instrucció «conserva l'original quan no hi hagi un benefici justificat» es va
implementar primer en la seva forma general: **cap** canvi superficial no cobra
guany si no millora alguna dimensió mesurada. És una regla defensable, però
contradiu un contracte del motor —«una transformació segura puntua positiu»,
fixat a `tests/test_scoring.py::test_safe_transformation_scores_positive`— i,
mesurat, canvia el resultat de **28 tests** existents que no tenen res a veure
amb aquest problema (CLI, canonada, epistemologia, diccionaris). Un canvi
d'aquesta mida és una decisió de producte, no una correcció d'abast acotat: es
deixa proposada i no aplicada. El que s'aplica és la forma estreta, que és la
que respon a la frase observada.

Tres tests de la branca (`test_regressions_1313`, `test_seleccio_1317`,
`test_seleccio_1318`) demanaven que dues causals arribessin a la selecció final.
Amb la regla nova ja no hi arriben, perquè totes dues degraden. S'hi ha conservat
la propietat que sí que hi és en joc —que una arquitectura repetitiva es
consideri i no guanyi, i que dues causals seguides mai no siguin la mateixa— i
s'ha tret l'exigència que en guanyés alguna.

### Estructures i variants

- L'abast estructural d'una transformació composta ara només compta el que hi
  han canviat les operacions estructurals. Abans, una substitució de connector
  absorbida dins d'una reordenació eixamplava la substitució física i, amb ella,
  el grau de reredacció: «Tanmateix, una peça no encaixa…» sortia amb 0,38 de
  grau estructural i «Però una peça no encaixa…» amb 0,25, tot i que
  l'operació estructural era la mateixa.
- En cas d'empat, la selecció tria el candidat amb **menys operacions reals**,
  incloses les que una transformació composta ha absorbit. Abans es comptaven
  només les transformacions físiques i dues operacions fusionades semblaven una.
- `structural_change_score` continua sent el mateix indicador estructural que
  ja era, exportat al JSON i pagat una sola vegada al component «estructura».
  L'etiqueta que en veu qui llegeix les dimensions passa a ser «indicador de
  canvi estructural» per no llegir-lo com un percentatge de millora.
- A la interfície, l'etiqueta «millor» del candidat guanyador passa a ser
  «preferit pel motor».

### Abans → després (mode profund, nivell 3, regles `parafrasi`)

| Frase | Abans | Després |
|---|---|---|
| La reina, quan apareix o quan es consolida, tampoc no necessita una explicació excessiva: ocupa el lloc… | Nivell efectiu 2 («el nucli "reina" no és un verb»); cap alternativa | Nivell 3; cap alternativa, amb la nota del bloc amb pronom feble |
| El rei no necessita gaire justificació: és el centre del tauler i el centre del regne. | Cap alternativa | El rei, que és el centre del tauler i el centre del regne, no necessita gaire justificació. |
| Però hi ha una peça que no encaixa tan fàcilment: l'orfil. | No obstant això, hi ha una peça que no encaixa tan fàcilment: l'orfil. | Però una peça no encaixa tan fàcilment: l'orfil. |
| Hi ha peces dels escacs que semblen haver conservat el seu nom perquè la seva funció era clara. | …ja que la seva funció era clara. | Sense canvi: l'única alternativa degrada l'estructura i no en reorganitza cap |

### Una regla d'ordre que no s'aplicava mai

Buscant per què la prosa expositiva rep tan poc canvi sintàctic, va aparèixer que
`ordre.connector_medial_a_inicial` («La hipòtesi, per tant, continua oberta.» →
«Per tant, la hipòtesi continua oberta.») no proposava res, ni tan sols per al
seu exemple declarat. La causa: la condició `has_finite_verb` es resolia amb
l'endevinador morfològic, que no reconeix formes tan corrents com «ocupa»,
«continua» o «roman». La regla ara demana l'analitzador, que és qui sap on és el
verb, i torna a funcionar.

La seva bessona, `ordre.connector_inicial_a_medial` («Per tant, S V…» → «S, per
tant, V…»), continua sense aplicar-se per un motiu diferent i més profund:
l'element `{np: true}` del motor de patrons no ofereix cap encaix més curt quan
el sintagma s'empassa el verb, de manera que el patró no arriba a encaixar. Es
documenta i no es toca: canviar el retrocés de l'element nominal afecta totes les
regles que en fan servir i necessita el seu propi mesurament.

## Bateria de proves

Bateria completa (`python -m pytest tests/ -q`) amb `ca_core_news_md` instal·lat,
comparada amb la mateixa bateria a `5c282dd` en un *worktree* a part:

| | HEAD `5c282dd` | Aquesta entrega |
|---|---|---|
| Passen | 746 | 801 |
| Fallen | 27 | 23 |
| S'ometen | 73 | 78 |

**Cap fallada nova.** Les 23 que queden ja fallaven a `5c282dd` i no tenen res a
veure amb aquests canvis. Se'n resolen quatre:
`test_rule_id_list_matches_rule_set`, `test_rule_set_covers_all_families`,
`test_rule_examples[assertiu.limitacio_documental]` (l'inventari de regles del
test no coincidia amb el conjunt real) i
`test_rule_examples[ordre.connector_medial_a_inicial]`.

## 4. Nivell de paràgraf

`tests/test_nivell5_focalitzat.py` comprova el camí sencer de la interfície
(mode profund, nivell 5) i confirma que les regles entre frases s'executen i
guanyen quan són aplicables:

```
El rei ocupa el centre. La reina es mou lliurement.
→ El rei ocupa el centre i la reina es mou lliurement.       (fusio.frases_compatibles)

L'orfil va perdre el nom llatí…. Un fet que explica la varietat de formes actuals.
→ L'orfil perdé el nom llatí…, un fet que explica la varietat de formes actuals.
```

Amb nivell 4 les mateixes frases no es fusionen, de manera que el que obre la
fase és el nivell demanat.

**El límit és de cobertura, no de configuració ni d'execució.** La fase de
paràgraf s'executa igualment quan no hi ha res a fusionar; el que no hi arriba
són les estratègies de `resources/ca/transformations/fusio.yaml`, que són
deliberadament estretes: `frases_curtes` no fusiona si la segona frase comença
per connector, demostratiu o còpula (`skip_if_second_starts_with`) ni si les
frases superen `max_words`/`max_words_each`, i `aposicio_anaforica` demana un
fragment nominal amb relativa. En prosa expositiva normal, la majoria de parells
de frases cauen fora d'aquestes condicions. Aquesta entrega no amplia la
cobertura de fusió.
