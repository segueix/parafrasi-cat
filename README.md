# parafrasi-cat

Motor **local** de reredacció i parafraseig en català, amb una interfície web
que s'executa al mateix ordinador.

> **El motor no utilitza LLM ni serveis generatius. La reredacció es produeix
> mitjançant regles lingüístiques explícites, recursos locals, anàlisi
> morfològica i sintàctica, validació gramatical i selecció determinista de
> candidats.**

**Versió 1.3.2.** Un cop instal·lats els recursos, tot funciona sense connexió.
Parafrasi-cat no envia text a serveis d'Internet: en mode local, el text no surt
del dispositiu; en mode de xarxa local, només circula entre el navegador client
i el servidor Parafrasi-cat dins de la LAN.

## Què és

- Un motor que **proposa variants** d'un text en català i n'explica cadascuna:
  quina regla l'ha generada, quin risc té i per què s'ha triat o descartat.
- Una eina **assistida**: mostra els candidats perquè una persona en triï un,
  l'editi i el validi.
- Un projecte de **recursos editables**: regles, diccionaris, preferències i
  feedback són fitxers que podeu llegir, modificar i versionar amb Git.

## Què no és

- **No és un LLM ni una API generativa.** No hi ha cap model generatiu ni cap
  crida a cap servei.
- **El parser sintàctic només analitza.** És un model estadístic d'anàlisi, no
  generatiu: no escriu text, no completa frases i no decideix res. Tota la
  generació surt de les regles.
- **No és un reescriptor autònom.** El resultat s'ha de revisar.
- **No inventa contingut.** No afegeix informació, no treu matisos i no
  resumeix.
- **No aprèn.** El feedback són recomptes explícits en un YAML.
- **No envia res enlloc.** Les úniques descàrregues són les d'instal·lació dels
  recursos, sempre amb confirmació.

## Principi fonamental

**El contingut original és intocable.** El motor pot canviar la *forma* d'una
frase, però no pot alterar noms propis, dates, xifres, números romans,
citacions, text entre cometes, terminologia protegida, negacions ni la força
epistemològica. Els detectors marquen els fragments intocables abans d'aplicar
cap regla i els validadors ho tornen a comprovar a cada candidat. Un candidat
que en trenqui cap queda invalidat i mai no se selecciona.

Parafrasi-cat utilitza morfologia, anàlisi sintàctica i validació gramatical
local per augmentar la seguretat de les transformacions. Quan aquests recursos
no ofereixen prou confiança, el motor prefereix conservar el text original.

## Instal·lació

Requereix Python 3.11 o superior.

```bash
git clone <url-del-repositori> parafrasi-cat
cd parafrasi-cat
pip install -e .
```

### Sense escriure cap ordre

| Sistema | Fitxer |
|---|---|
| Windows | `start_parafrasi.bat` |
| macOS | `start_parafrasi.command` |
| Linux | `start_parafrasi.sh` |

Feu-hi doble clic: instal·la el que calgui la primera vegada i obre la
interfície al navegador.

## Com obrir la web

```bash
parafrasi-cat web                       # obre http://127.0.0.1:8765/
parafrasi-cat web --port 9000 --no-browser
parafrasi-cat web --lan                 # també des de la xarxa local, amb codi d'accés
```

Per defecte el servidor es lliga a l'amfitrió local i la pàgina no carrega cap
recurs extern. Amb `--lan` escolta a totes les interfícies d'aquesta màquina i
demana un codi d'accés de sis xifres: vegeu
[«Utilitzar Parafrasi-cat amb dos Chromebooks»](#utilitzar-parafrasi-cat-amb-dos-chromebooks).

## Mode lingüístic complet i mode bàsic

El motor treballa en un de dos modes, segons el que hi hagi instal·lat:

| | Mode lingüístic complet | Mode bàsic |
|---|---|---|
| Morfologia de Softcatalà | sí | reserva interna |
| Parser sintàctic | sí | heurístiques |
| LanguageTool local | sí | validadors interns |
| Cobertura | més alta | més baixa |
| Prudència | la de sempre | encara més alta |

La interfície ho diu en una línia: **«Mode lingüístic complet actiu»** o **«Mode
bàsic: instal·la els recursos lingüístics per obtenir més cobertura.»**
Parafrasi-cat **no falla mai** perquè falti un recurs; simplement transforma
menys i conserva l'original més sovint.

## Com instal·lar els recursos

La secció **Recursos lingüístics** de la interfície mostra l'estat de cada
component:

```
Morfologia catalana      ✓ activa
Parser sintàctic català  ✓ activa
LanguageTool local       ✓ actiu
Java                     ✓ disponible
Mode fora de línia       ✓ disponible
```

Si en falta algun, hi surt un botó per instal·lar-lo. **Abans de baixar res** es
mostra el component, l'origen, la versió, la mida aproximada i la llicència, i
cal confirmar-ho explícitament. Després no cal connexió per a res.

Des del terminal, si ho preferiu:

```bash
python scripts/install_morphology.py     # diccionari de Softcatalà (cal git)
python scripts/install_parser.py         # spaCy + model català
python scripts/install_languagetool.py   # LanguageTool (cal Java)
```

Cap dels tres és obligatori: sense ells, el motor funciona en mode bàsic amb
els seus components interns.

## Com crear una empremta d'autor

A la secció **Empremta de l'autor**: poseu-hi un nom, trieu els vostres textos
`.txt` o `.md` i premeu **Crea l'empremta**. L'anàlisi es fa en aquest
ordinador, els textos no van a Internet i **no s'entrena cap model**: només se'n
desen recomptes i estadístics robustos a `style/<nom>.json`.

També des del terminal:

```bash
parafrasi-cat style build corpus/author/ --profile resources/style/autor.yaml
parafrasi-cat style show style/autor.json
```

## L'empremta: estructura i ritme

Des de la 1.2, l'empremta no descriu només *quines paraules* fa servir
l'autor, sinó *com escriu*:

| Secció | Què registra |
|---|---|
| `rhythm_profile` | longitud de frase en tokens lingüístics (paraules, clítics i xifres, sense puntuació): mitjana, mediana, desviació, coeficient de variació, percentils; franges curta / mitjana / llarga amb llindars derivats del corpus (tercils); matriu de transició entre franges; trigrames; ratxes; correlació de retard 1; canvi absolut mitjà; paràgrafs, si el text els conserva |
| `syntactic_profile` | amb el parser local: coordinació (per frase, per tipus, mida dels grups, conjuncions), subordinació (relatives, adverbials, completives, infinitives; profunditat), ordre del subjecte i dels complements, distància de dependències, complexitat (clàusules, profunditat de l'arbre) i patrons abstractes com «TEMP + MAIN» o «MAIN + REL» |

Cap de les dues seccions no guarda frases del corpus: només estadístics,
distribucions i patrons abstractes. Cada secció porta la mida de la mostra i
una confiança (`low`, `medium`, `high`) amb criteri documentat: `high` amb 40
frases o més en 2 documents o més, `medium` amb 15 o més, `low` la resta. Amb
menys de 12 frases, els llindars de franja són els de reserva (curta ≤ 12,
llarga ≥ 25) i queden marcats com a tals; amb menys de 6 parelles de frases
consecutives, la correlació de retard 1 és `null`. Una mètrica amb confiança baixa no entra
mai a la puntuació.

El parser sintàctic (spaCy, UD Catalan AnCora) **només analitza**: aporta
dependències, categories i trets i el motor en fa recomptes. Sense el parser
instal·lat, el perfil sintàctic queda marcat com a no disponible. Les
empremtes antigues (esquema 1.0) es carreguen igualment; la interfície diu què
els falta i proposa tornar-les a crear amb els teus textos.

A la web, en triar una empremta apareix la secció **Estructura i ritme**:
longitud típica, variació, proporció curta / mitjana / llarga, tendència
d'alternança (amb la matriu de transició en paraules: «Curta → Llarga: molt
freqüent»), coordinació, subordinació, ordre predominant del subjecte,
complexitat i confiança de la mostra, amb un «Veure detalls» tècnic.

En la puntuació de candidats, l'afinitat amb l'autor incorpora dos components
més: **ritme** (`rhythm_similarity_score`: la seqüència de longituds del
document amb el candidat al seu lloc, comparada amb la de l'autor) i
**sintaxi** (`syntactic_similarity_score`: taxes de coordinació, subordinació,
ordre, distància, profunditat i familiaritat dels patrons). Amb text propi
compten com a desempat lleu entre candidats segurs; amb un esborrany generat
amb LLM, amb tot el pes. Continuen per sota dels invariants: cap ritme no
compensa un fet perdut. L'empremta descriu tendències, no una plantilla: no es
força cap paràgraf a reproduir-ne les proporcions.

La biblioteca TextDescriptives s'ha avaluat i descartat: arrossega pandas,
numpy < 2, pyphen, ftfy i pydantic, i les mètriques necessàries (distància de
dependències, estadístics de longitud, recomptes de dependències) són trivials
d'implementar sense cap dependència nova. Estan a `style/rhythm.py` i
`style/syntax_profile.py`.

## Com parafrasejar

Des de la interfície: enganxeu o carregueu el text, trieu nivell, empremta,
diccionaris, preferències i mode, i premeu **Genera candidats**. Per a cada
frase i paràgraf veureu el text original, el millor candidat, la resta de
candidats, les diferències, les regles aplicades, les puntuacions per dimensió
i els advertiments de validació. Podeu marcar candidats, editar el resultat i
copiar-lo o exportar-lo.

Des del terminal:

```bash
parafrasi-cat rewrite text.txt --level 5
parafrasi-cat rewrite text.txt --style style/autor.json \
  --dictionary dictionaries/historia.yml --preferences preferences/author.yml
parafrasi-cat --rules parafrasi --explain "Gairebé sempre plou, tot i que avui no."
```

## Origen del text

A la interfície es pot indicar d'on ve el text:

- **Text propi** (per defecte): el comportament de sempre.
- **Esborrany generat amb LLM**: s'hi afegeix una capa d'**adaptació
  autoral** basada en l'empremta real de l'autor. És obligatori tenir-ne una
  seleccionada; si no, la interfície ho diu i deixa crear-la allà mateix.

El mode d'esborrany LLM no intenta determinar ni ocultar l'origen del text.
Utilitza l'empremta estilística de l'autor per prioritzar reformulacions més
coherents amb la seva manera real d'escriure.

No pregunta «això sembla humà?», sinó «aquest candidat s'assembla més a la
manera d'escriure d'*aquest* autor?». Mesura, amb estadística descriptiva i
de manera determinista, l'**afinitat amb l'estil** de cada candidat:

| Component | Què compara |
|---|---|
| Longitud de frases | franja i mediana del candidat, i dispersió del document, amb la distribució de l'autor |
| Connectors | sobreús respecte del corpus i familiaritat de cada connector |
| Puntuació | comes, punts i coma, dos punts, parèntesis i incisos per frase |
| Terminologia | si conserva els termes que l'autor i el document repeteixen |
| Construccions | impersonals i passives per cent frases |

L'afinitat suma o resta *respecte de l'original*, i sempre per sota dels
invariants: cap estil no compensa la pèrdua d'un fet, una data, un nom, una
negació, un augment de certesa ni un error gramatical. Cada candidat mostra la
seva afinitat i per què («menys sobreús de connectors», «longitud de frases més
propera a l'empremta», «substitueix terminologia que l'autor manté»).

Els textos marcats com a esborrany **no entren mai** al corpus de l'autor: la
interfície s'hi nega, perquè contaminarien l'empremta. No hi ha cap LLM, cap
generació neuronal ni cap detector d'IA; el parser sintàctic, si hi és, només
analitza; i tot funciona localment.

Des del terminal: `parafrasi-cat rewrite text.txt --style style/autor.json --source-mode llm_draft`.

## Modes

| | Conservador | Reredacció profunda |
|---|---|---|
| Risc semàntic màxim | baix | mitjà |
| Confiança mínima | 0,75 | la del conjunt de regles (0,55) |
| Transformacions per candidat | 1 | fins a 3 |
| Reaplicació de regles | no | sí |
| Nivell màxim | 3 | 5 |

El **conservador** només accepta canvis clarament segurs i, si no n'hi ha cap,
conserva l'original. El **profund** arriba fins al nivell 5 i combina
transformacions. Cap dels dos no pot tocar cap protecció: els termes protegits,
els diccionaris, les preferències i la llista de validadors són idèntics.

## Nivells 1-5

| Nivell | Abast | Regles |
|---|---|---|
| 1 | Lèxic | 3 |
| 2 | Connectors | 7 |
| 3 | Sintaxi: còpula, agent, presència, ordre, temporals, subordinades, impersonals | 40 |
| 4 | Entre frases: divisió i puntuació | 3 |
| 5 | **Reestructuració controlada de paràgraf** | 2 |

El **nivell 5 és diferent del 4**: activa una fase de paràgraf que reorganitza
frases senceres (fusió amb represa anafòrica, fusió copulativa, integració d'un
fragment nominal anafòric) i, en mode profund, **compara arquitectures
alternatives de paràgraf**: en lloc de reconstruir el paràgraf amb el candidat
que guanya a cada frase, una cerca en feix determinista i acotada conserva uns
quants candidats segurs i diversos de cada frase (l'original, el millor i el
millor de cada família estructural), aplica les regles de paràgraf on són
possibles i tria l'arquitectura sencera que puntua millor, amb l'afinitat de
l'autor mesurada sobre tot el paràgraf. Un candidat que queda segon en una
frase pot guanyar si dona un paràgraf millor; el resultat ho explica. El nivell
4 treballa dins de cada frase i no arriba a aquesta fase. Les proteccions són
exactament les mateixes als dos nivells.

El **grau estructural** d'un candidat només mesura l'arquitectura lingüística:
reordenacions, subordinació, canvis de construcció, divisions i fusions. Les
substitucions lèxiques, de connector, de puntuació i la flexió verbal («va
gaudir» → «gaudí») tenen grau estructural 0 i es recullen a part com a **grau
superficial**; repetir la mateixa família té rendiments decreixents, i una
transformació que degrada l'estructura local (dues relatives consecutives amb
el mateix marcador, «que» acumulats) rep una penalització, mai una invalidació.

Reestructurar en profunditat **no vol dir escriure més llarg**. Abans de
fusionar res, el motor calcula la longitud de la frase resultant i la compara
amb el que l'autor acostuma a escriure —el seu `max_sentence_length`, la
distribució de la seva empremta o la longitud que ha declarat preferir— i mana
la més restrictiva. Si se'n va, la fusió no es proposa i el resultat ho diu:

```
ℹ no s'han fusionat «La primera referència itàlica…» i «En aquest sarcòfag…»:
  tindria 32 paraules i el límit és 25 segons el màxim de 25 de l'autor
```

Amb un autor de frase curta, la reestructuració del nivell 5 recau en la
divisió i la reordenació; amb un autor de períodes llargs, la fusió continua
disponible dins dels límits observats.

## Morfologia

El diccionari de Softcatalà aporta lema, categoria, gènere, nombre, persona,
temps i mode d'1.188.611 formes. Les regles hi conjuguen en lloc de fer servir
parelles escrites a mà:

```yaml
transformation: "{cop|inflect(constituir,és=constitueix,són=constitueixen)}"
```

La prioritat és explícita: **recurs morfològic → mapatge declarat → heurística →
no transformar**. Els mapatges es conserven com a reserva, de manera que sense
el recurs el motor es comporta com abans.

## Parser sintàctic

spaCy amb `ca_core_news_sm` (UD Catalan AnCora) aporta dependències, subjecte,
objecte, subordinades i coordinacions. Les regles el consulten **només si el
demanen**:

```yaml
conditions:
  syntax:
    requires_parser: true
    subject_number: pl
    no_clause_boundary: true
```

Una regla sense bloc `syntax` no el consulta mai i no canvia de comportament.
Si el parser no hi és i la regla l'exigeix, la regla no s'aplica: davant del
dubte, no es transforma. Si el parser i els invariants de seguretat es
contradiuen, manen els invariants.

### Confiança sintàctica

El parser **no es considera infal·lible**. Cada anàlisi passa un criteri
explícit abans d'autoritzar res estructural:

1. hi ha mots analitzats;
2. hi ha exactament una arrel (dues arrels són dos fragments);
3. cap dependència no surt de la frase ni forma un cicle;
4. hi ha almenys un verb conjugat;
5. el nucli és un verb o un predicat amb còpula;
6. el parser ha sabut classificar totes les relacions;
7. la morfologia local no el contradiu en el nombre del subjecte ni del verb.

Si la frase no el supera —un fragment nominal, una estructura incompleta, una
contradicció—, **no es força cap anàlisi**: les transformacions d'aquella frase
es limiten al nivell 2 (lèxic i connectors) i el resultat diu per què:

```
ℹ anàlisi sintàctica poc fiable: no hi ha cap verb conjugat: sembla un
  fragment nominal; només s'han provat transformacions fins al nivell 2
```

### Concordança

Amb parser i morfologia, el motor comprova la concordança de subjecte i verb de
cada candidat i **només compta les discordances que ha introduït ell**: les que
ja eren al text de l'autor no descarten res i tampoc no s'esmenen sols.

Si la discordança és seva i la morfologia local dona **una sola** forma
possible, la corregeix i la correcció queda registrada com una transformació
més (`concordanca.reparacio`), amb el seu perquè. Si hi ha més d'una forma
possible, o cap, no s'inventa res: el candidat es descarta.

## LanguageTool

Comprova gramàtica, concordança i puntuació de cada candidat. **Només valida**:
no genera la paràfrasi, no reescriu el text i no aplica cap correcció. El motor
de candidats és qui decideix si un candidat es penalitza o es descarta.

El servidor local s'arrenca **una sola vegada** per sessió i es reutilitza, amb
comprovació d'estat, reinici si cau i tancament net. Mai no es fa servir l'API
de languagetool.org.

### Errors nous contra errors de l'original

El motor compara els problemes de l'original amb els del candidat i es fixa
només en els **nous**. Cada problema nou es classifica segons on cau:

| Gravetat | Quan | Efecte |
|---|---|---|
| Bloquejant | error gramatical nou dins del fragment transformat | invalida el candidat |
| Penalització forta | el mateix error lluny del canvi, o puntuació i ortografia dins del canvi | baixa molt la puntuació |
| Advertiment | estil, repeticions, preferències | baixa la puntuació |
| Informatiu | el problema ja hi era, o no implica incorrecció | cap |

Així un avís de LanguageTool sobre un nom propi de l'autor, que el motor no ha
tocat, ja no descarta la reescriptura sencera. I quan sí que descarta un
candidat, ho diu amb noms i cognoms:

```
✘ Candidat rebutjat: LanguageTool: la regla «copula.es_a_constitueix» ha
  introduït: Possible error de concordança. (CONCORD_SUBJECTE_VERB)
```

La negació, les xifres, els noms propis i la força epistemològica no es deixen
en mans de LanguageTool: els guarden els invariants del motor.

## Diccionaris

Diccionaris terminològics per projecte a `dictionaries/*.yml`, combinables:

```yaml
entries:
  - term: sarcòfag
    preferred: [sarcòfag]
    accepted: [sarcòfag funerari]
    avoid: [fèretre]
    protected: true
```

Un terme `protected` passa a ser un fragment protegit: **cap regla estilística
no el pot sobreescriure**.

## Preferències

`preferences/author.yml` recull les preferències explícites de l'autor: formes
preferides i evitades, connectors, longituds de frase i pesos de variants.

Jerarquia de prioritats: fragments protegits explícitament → termes protegits
dels diccionaris → formes dels diccionaris → preferències de l'autor i feedback
→ empremta estadística → preferències generals del motor.

## Feedback

Marcar una variant com a **preferida**, **acceptable** o **rebutjada** suma un
recompte a un YAML llegible. El pes és la mitjana d'aprovació suavitzada amb un
prior, de manera que cap decisió aïllada no capgira les preferències. No
s'entrena res.

## Traçabilitat

Registre local **opcional i desactivat per defecte**. Amb el registre
desactivat no s'escriu res. Quan s'activa, cada reescriptura desa una línia JSON
amb el text original, la data, la configuració, els candidats, les puntuacions,
el candidat seleccionat, les regles, el feedback i l'edició final.

## Utilitzar Parafrasi-cat amb dos Chromebooks

Un Chromebook pot fer de servidor i un altre, de client:

- **Chromebook 1**: ChromeOS amb Linux, parafrasi-cat i tots els recursos
  lingüístics. S'engega amb `parafrasi-cat web --lan` (o `start_parafrasi_lan.sh`)
  i mostra un codi d'accés de sis xifres, nou a cada arrencada.
- **Chromebook 2**: només Chrome. Obre `http://IP-DEL-CHROMEBOOK-1:8765`,
  escriu el codi i fa servir la mateixa interfície de sempre. No li cal Linux,
  Python, Java, spaCy, LanguageTool ni Git.

El resultat lingüístic és **idèntic** al del mode local: el mode de xarxa local
només canvia per on viatja el text, no què fa el motor. Sense `--lan`, el
servidor continua escoltant només a `127.0.0.1` i no demana cap codi.

Si s'escriu el codi malament deu vegades seguides, el servidor deixa
d'acceptar-ne cap durant un minut: així no es poden provar les sis xifres una
per una.

La guia completa —instal·lació, redirecció de ports de Crostini, quina adreça
IP cal fer servir, seguretat i privacitat— és a
[`docs/chromebook-dual.md`](docs/chromebook-dual.md).

## Fora de línia

Cap component consulta Internet durant el parafraseig, l'anàlisi, la validació,
la puntuació, la selecció, el feedback o l'exportació. Les úniques connexions
possibles són amb aquest mateix ordinador —el navegador amb la interfície, i la
interfície amb el servidor local de LanguageTool— i, si s'activa el mode de
xarxa local, amb el navegador d'un altre dispositiu de la mateixa LAN. Els
tests ho comproven bloquejant tota connexió que no sigui de bucle local.

## Com afegir una regla

1. Afegiu la definició a `resources/ca/transformations/<família>.yaml` amb
   `rule_id`, `engine`, `category`, `level`, `semantic_risk`, `confidence`,
   `pattern`, `transformation`, `conditions`, `exceptions` i **exemples
   positius i negatius**.
2. Si és una família nova, incloeu el fitxer a `rules/parafrasi.yaml`.
3. Afegiu el `rule_id` a `RULE_IDS`, a `tests/test_regles_definicions.py`.
4. Executeu `make check`.

## Desenvolupament

```bash
make test        # pytest
make lint        # ruff
make typecheck   # mypy en mode estricte
make check       # tot
```

## Limitacions conegudes

- **La cobertura és limitada.** Amb 40 regles, moltes frases no encaixen amb cap
  i es retornen sense canvis. La v1.0 prefereix no transformar abans que
  arriscar el significat.
- **El parser no és infal·lible.** És un model estadístic entrenat sobre AnCora:
  encerta la majoria de casos, però no tots. Per això les regles que el fan
  servir exigeixen confiança i, quan no n'hi ha, no transformen.
- **Les regles s'han desenvolupat sobre un corpus petit.** El rendiment sobre
  text arbitrari serà inferior al dels exemples del repositori.
- **En mode bàsic la comprovació és més fina.** Sense parser ni LanguageTool,
  el validador intern detecta contraccions incorrectes, signes desaparellats i
  defectes de puntuació, però no la concordança ni el règim verbal.
- **El perfil sintàctic depèn del parser.** Les relatives es reconeixen pel
  pronom relatiu i les passives pel participi amb «ser» o per `expl:pass`,
  perquè el model no distingeix `acl:relcl` ni `nsubj:pass`; els complements
  locatius gairebé mai no es poden classificar. En cas de dubte no es compta.
- **La concordança que es comprova és la de subjecte i verb.** No es comprova
  la de determinant i nom ni la dels participis, i els subjectes col·lectius
  («la majoria dels autors») queden fora expressament: hi són correctes totes
  dues concordances.
- **La primera comprovació amb LanguageTool és lenta** (uns segons), perquè el
  servidor local hi carrega el model català. Les següents són immediates.

## Llicència

GPL-3.0-or-later. Vegeu [`LICENSE`](LICENSE) i, per a les atribucions de cada
component, [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

Documentació addicional: [`docs/recursos-linguistics.md`](docs/recursos-linguistics.md),
[`docs/arquitectura.md`](docs/arquitectura.md),
[`docs/principis-de-preservacio.md`](docs/principis-de-preservacio.md),
[`CHANGELOG.md`](CHANGELOG.md).
