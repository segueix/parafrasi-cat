# Registre de canvis

El format segueix [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/) i el
projecte utilitza [versionatge semàntic](https://semver.org/lang/ca/).

## Pendent de publicació

- Els moviments de subordinades reconeixen els connectors amb majúscula:
  conserven la coma concessiva, adapten «Com que» a «ja que» en posició final
  i mantenen el bloqueig de «Perquè» final amb subjuntiu.
- Desactivada per defecte la divisió dels dos punts explicatius: tenir dues
  clàusules verbals no garanteix conservar la relació discursiva amb un punt.

- L'estil es compta una sola vegada sobre el prefix i el paràgraf complet,
  sense acumular les distàncies estilístiques de cada frase. Es mantenen els
  pesos, les preferències explícites i tots els validadors.
- Amb empremta, els paràgrafs següents veuen el text ja seleccionat dels
  anteriors, incloses divisions i fusions. No s'afegeixen passades ni s'amplia
  el beam. El futur continua referenciat a l'original.
- Regressió amb el corpus acadèmic d'exemple i mode esborrany: el text de
  l'orfil ja no introdueix «Tanmateix… Tanmateix» entre paràgrafs. Comprovat
  sense parser ni LanguageTool; aquesta correcció no modifica el parser ni
  elimina el seu possible soroll en la puntuació sintàctica.

## 1.3.17

La selecció final ja no es pot guanyar acumulant premis del mateix fet, i el
desempat estilístic existeix sempre. Sense reduir gens la capacitat de
reredacció de la v1.3.16.

### Causa real

Dos defectes independents, tots dos reproduïts sobre el paràgraf de l'orfil
abans de tocar res:

- **El desempat de repetició de connectors estava condicionat a
  `rewrite_pressure > 0`**, és a dir, només s'aplicava als esborranys d'LLM. Amb
  text propi, les dues arquitectures competidores empataven **exactament** a
  -0,2036 i guanyava la repetitiva per ordre d'arribada. Aquesta és la causa del
  cas reportat: no és que l'arquitectura més estructural s'imposés, és que el
  criteri que havia de desempatar no existia.
- **El grau estructural es cobrava dues vegades a la mateixa frase**: al bonus
  d'estructura (`w.structure · grau`) i, un altre cop, dins de la pressió de
  reescriptura (`w.rewrite_pressure · 0,65 · grau`). Amb els pesos del mode
  profund i esborrany, una sola reordenació valia 0,94 · grau ≈ 0,61, sis
  vegades el desempat estilístic més gran (0,18). Cap criteri d'estil no podia
  decidir mai entre dues arquitectures comparables.

### Un sol pagament per la reredacció

- La preferència per la reredacció és ara **un únic component** amb el mateix
  pes total que abans: `estructura = (w.structure + 0,65 · w.rewrite_pressure) ·
  grau · gramaticalitat · qualitat · ritme`. La pressió de reescriptura només
  paga el que el grau no mesura, la distància superficial respecte de
  l'original: `0,35 · w.rewrite_pressure · grau_de_canvi`.
- Amb el ritme intacte, la suma dels dos components és idèntica a la de la
  v1.3.16 (verificat als tests): la capacitat de reredacció no baixa gens. La
  diferència apareix on hi havia d'aparèixer: una fusió que trenca el ritme de
  l'autor perdia només la meitat del premi (la part estructural de la pressió
  no estava escalada pel ritme) i ara el perd sencer.

### El desempat estilístic no depèn de l'origen del text

- La repetició de connectors es mesura sempre que hi ha un inventari, amb text
  propi i amb esborrany. El que evita qualsevol diversificació agressiva no és
  el mode d'origen sinó la mesura mateixa: només es penalitza la repetició que
  el candidat **introdueix**; conservar la de l'autor continua sent gratuït.

### Comprovació sobre el text real

Amb les tres configuracions provades (text propi, esborrany amb empremta i
esborrany sense empremta), el paràgraf de l'orfil ja no repeteix la mateixa
causal: la reordenació de la frase del roc es conserva i el connector de la
frase del cavaller varia. La repetició introduïda per paràgraf és 0,00.

### Tests

`tests/test_seleccio_1317.py`: el grau es paga una sola vegada, la pressió
només paga la distància superficial, el pes total es conserva, una fusió que
trenca el ritme perd tot el premi, el desempat funciona sense pressió de
reescriptura, cap criteri estilístic no rescata un candidat invalidat, la
diversitat estructural continua guanyant un retoc superficial, la composició
profunda de la v1.3.16 continua viva, i sobre el text de l'orfil: cap repetició
introduïda, l'arquitectura repetitiva existia i ha perdut, la reredacció real
manté l'avantatge sobre l'original, «només … si» i els dos punts es conserven,
no es genera «puix que» i el resultat és determinista.

Les versions 1.3.15 i 1.3.16 estan documentades a l'historial de git.

## 1.3.14

Cerca de candidats: la reserva inicial ja no pot deixar l'expansió estructural
sense marge, i les places finals van a candidats que ja han passat la
validació. No s'ha ampliat cap regla ni s'ha relaxat cap validador, risc ni
confiança.

### El problema

Amb la configuració profunda, la reserva de treball és de 84 candidats i la
tria final en conserva 24. Les transformacions soltes i les seves combinacions
omplien la reserva sencera abans que l'expansió de segon nivell hagués
començat: amb vuit propostes independents ja se n'arriben a construir 92
(8 soltes + 28 parelles + 56 tríades), i el bucle d'expansió es trobava la
reserva plena i no feia **cap** crida. A més, el feix d'expansió s'ordenava per
la suma de confiances, de manera que tres retocs lèxics (0,95 × 3) sempre
desplaçaven una reordenació segura (0,70), que és justament la que més pot
guanyar amb una segona passada.

### Pressupost propi per a l'expansió

- `CandidateGenerator` accepta `expansion_budget` (per defecte, el doble de
  l'amplada del feix) i el reserva **per damunt** de la reserva base:
  `work_limit = pool_limit + expansion_budget`. Encara que les combinacions
  inicials la saturin, la reaplicació de regles sempre té marge.
- El feix d'expansió s'ordena per diversitat estructural (grau estructural,
  després confiança acumulada, després ordre de generació) i reserva un lloc a
  cada signatura abans de repetir-ne cap.

### Admissió abans de repartir les places

- La selecció final pot consultar una funció d'admissió que **repara, valida i
  puntua** el candidat. Els que no superen la validació no ocupen cap plaça —la
  hi aprofita una alternativa vàlida— però es retornen a part
  (`GenerationResult.rejected`) perquè el resultat continuï explicant per què
  s'han descartat.
- La canonada li dona aquesta funció amb memòria cau: cada candidat es repara,
  es valida i es puntua **una sola vegada**, i el pas d'avaluació reutilitza la
  mateixa cau. La reparació de concordança, que abans es feia en un pas a part
  sobre els candidats ja triats, ara forma part de l'admissió.
- L'original es conserva sempre i els desempats continuen sent estables (grau
  estructural, confiança acumulada, ordre de generació).

### Traça de la cerca

`SentenceResult.generation` (i el camp `generation` de l'API i de l'informe)
diu quantes propostes hi havia, quants candidats s'han construït, quants els ha
aportat l'expansió i en quantes reanàlisis, quants s'han avaluat, quants s'han
conservat, si la cerca ha arribat al seu límit de treball i per què cau la
resta: `duplicat`, `canvi excessiu`, `pressupost` (no cabia a la reserva),
`seguretat` (no supera la validació) i `puntuació` (l'han desplaçat candidats
millors).

### Cost

Sobre text real (paràgraf de l'orfil i text acadèmic de deu frases, mode
profund nivell 5), el temps d'execució no canvia: 2,06–2,48 s i 3,87–4,13 s
contra 2,10–2,42 s i 3,93–4,25 s abans. Cap frase del corpus del projecte no
satura avui la reserva —calen vuit propostes compatibles a la mateixa frase—,
de manera que el canvi és sobretot una correcció de robustesa per a frases
llargues amb moltes regles aplicables; el que sí que millora a tot arreu és que
les places finals no se les enduguin candidats invàlids.

### Tests

`tests/test_cerca_candidats.py`: saturació amb variants superficials i
supervivència de l'expansió, diversitat estructural al feix, expansió que
produeix una alternativa que la generació base no pot construir, admissió que
no gasta places en candidats invàlids, una sola consulta per candidat,
conservació de l'original, traça dels descartaments, límits acotats,
determinisme i, a la canonada, proteccions i explicació dels rebutjats.

## 1.3.13

Tria entre connectors equivalents dins d'un paràgraf: el motor deixa
d'introduir repeticions que l'original no tenia («atès que… atès que» on hi
havia «perquè… perquè») quan existeix una alternativa igual de segura. La
repetició continua sent legítima: la que l'autor ha escrit no es toca, i cap
frase no canvia si no hi ha cap candidat segur.

### Per què encara guanyava «atès que… atès que»

Tres causes independents, totes tres corregides:

- **La mesura no veia els connectors que discutia.** El recompte de la v1.3.11
  es feia sobre `UnitStats.connectors`, que surt de l'observació d'estil: les
  formes de més d'una paraula lexicalitzades com a conjunció («atès que», «ja
  que», «com que») no hi arriben mai, perquè l'observador només mira
  expressions de classe connector o marcador i tokens solts. El perfil de
  connectors d'un paràgraf amb dos «atès que» sortia buit, i la penalització
  valia zero.
- **Només mirava aparicions consecutives.** Dues repeticions separades per un
  altre connector no comptaven, per pròximes que fossin.
- **Penalitzava l'original i no el candidat.** Com que es mesurava el candidat
  sol, un paràgraf que ja repetia «perquè» rebia la penalització, i el candidat
  que hi introduïa «atès que… atès que» no en rebia cap.

### Repetició de connectors mesurada de nou (`style/connector_repetition.py`)

- **Inventari accionable**: les formes que declaren les classes d'equivalència
  de connectors de les regles actives (membres i objectius). Són exactament les
  que el motor pot intercanviar; les formes que no pot variar no hi entren, i
  els marcadors d'interacció col·loquial («home», «escolta») tampoc. Es
  reconeixen sobre els tokens, de manera que les formes de més d'una paraula ja
  no depenen del lexicó d'expressions.
- **Distància**: cada aparició es compara amb l'anterior de la mateixa forma i
  pesa `1 / (1 + frases de distància)`: 1,00 dins de la mateixa frase, 0,50 a
  la següent, 0,33 dues més enllà, 0,25 tres… Decreix sempre, és acotat i no té
  cap llindar. Fora de la unitat que es puntua no es mesura res.
- **Introduïda contra heretada**: es compara la severitat per forma del
  candidat amb la de l'original i només es penalitza l'excés. Conservar
  «perquè… perquè» no costa res; substituir-ho per «atès que… atès que» sí,
  perquè la forma nova no era repetida a l'original.

### El feix conserva els perfils de connectors

- Els candidats locals porten anotats els connectors que contenen
  (`LocalOption.connectors`), i cada estat el seu perfil acumulat.
- `_prune` guanya una capa: després del millor estat i del millor estat de cada
  candidat de la frase acabada d'afegir, es conserva el millor estat de cada
  perfil de connectors recent (els dos darrers). Dues arquitectures amb les
  mateixes signatures que difereixen només en un connector triat unes frases
  enrere ja no es maten entre elles. Tot continua acotat per l'amplada del feix:
  cap capa no hi afegeix ni un estat de més.
- Els prefixos del feix es puntuen contra el prefix **original** del paràgraf,
  no contra el text intermedi, de manera que la cerca optimitza el mateix
  objectiu que la selecció final.

### La decisió es pren una sola vegada, sobre el paràgraf sencer

- La repetició és una propietat del paràgraf. Les puntuacions de frase ja no
  se sumen amb la seva aproximació: el component `repeticio_connectors` es
  descompta del total de frases (com ja es feia amb l'afinitat autoral) i es
  torna a mesurar una sola vegada sobre l'arquitectura completa, contra el
  paràgraf original. No hi ha cap bonus nou ni cap doble recompte.
- **Un canvi que recrea una repetició no cobra el guany que cobrava.** Amb una
  penalització fixa i petita, afegir un segon canvi de connector idèntic sempre
  sortia a compte: el premi per transformació (0,19) superava la penalització
  (0,09). Ara, en proporció a la severitat, les frases que porten la forma
  repetida perden exactament el guany que el mateix puntuador els havia
  concedit per aquell canvi. No hi ha cap constant nova ni cap pes inflat: el
  pes `connector_repetition` continua sent 0,18.

### Traçabilitat

`ScoreBreakdown.connectors` i cada arquitectura del feix exposen el perfil de
connectors, les repeticions detectades amb la seva distància, quines són noves
respecte de l'original i la penalització resultant. El motiu de conservació de
cada estat del feix diu si ha sobreviscut pel seu perfil de connectors.

### Altres

- `Pipeline.scorer` és accessible com les altres peces de la canonada.
- La versió que declarava el paquet (`parafrasi_cat.__version__`) s'havia quedat
  a la 1.3.3 mentre `pyproject.toml` avançava; ara tornen a coincidir. Les
  versions 1.3.4 a 1.3.12 estan documentades a l'historial de git.
- Tests nous (`tests/test_regressions_1313.py`): inventari, formes de més d'una
  paraula, decaïment per distància, introduïda contra heretada, connectors
  equivalents diferents sense penalització, absència de referència, veïnatge,
  traça, diversitat de perfils al feix, poda acotada, guany retirat, text real
  de l'orfil amb totes les proteccions anteriors i determinisme.

## 1.3.3

Més cobertura d'alternatives segures al nivell 5 del mode profund, sense
augmentar l'agressivitat, i opció «Llenguatge assertiu» a la interfície. El
patró «0 – 0 – 0 – 0 – transformació forta – transformació forta – 0» d'un
paràgraf acadèmic real (deu frases) passa a set frases amb alternativa segura,
sis d'elles estructurals; les tres restants queden intactes perquè no tenen
cap alternativa segura, i el resultat ho diu.

### Cobertura estructural: capa de transformacions intermèdies

- Regla nova `ordre.pero_medial_a_inicial`: «La hipòtesi no depèn, però, d'una
  sola coincidència» → «Tanmateix, la hipòtesi no depèn d'una sola
  coincidència» (i «No obstant això, …»). Reordenació discursiva lleu
  (`structural_weight` 0,4), sense cap substitució lèxica que no vingui d'un
  diccionari explícit.
- La detecció de verb conjugat sense analitzador consulta el recurs morfològic:
  una forma que el diccionari només coneix com a verb conjugat («permetria»,
  «continuaria») compta encara que no sigui a la llista de formes freqüents ni
  l'endevini cap sufix; dins d'un fragment protegit («Benedetto *da*
  Rovezzano») no hi ha mai cap verb. Amb l'analitzador, una forma conjugada que
  el parser etiqueta malament («continuaria» com a adjectiu) també la salva el
  diccionari. `divisio.coordinada_pero` torna a dividir «…continuaria sent
  hipotètica, però permetria ordenar…».
- L'analitzador rep el text amb els apòstrofs tipogràfics normalitzats
  (`prepare_text`): «d’aquest» deixava el parser sense arrel fiable i bloquejava
  totes les transformacions guiades per la sintaxi sobre textos reals. Les
  superfícies originals es conserven als tokens i als resultats.

### Moviment de blocs sintàctics complets (`block_move`)

- Motor nou `rules/blocks.py` i regles `blocs.subordinada_adverbial`
  (condicionals, causals, concessives, temporals, finals: inicial ↔ final, amb
  els marcadors que canvien de forma segons la posició: «perquè» → «com que»),
  `blocs.complement_del_verb` (complement circumstancial de tres o més paraules
  cap a l'inici) i `blocs.participial_del_subjecte` (participial interposat del
  subjecte cap al davant, dins de la seva clàusula: «El problema principal és
  que, considerat de manera aïllada, cap d'aquests elements permet…»).
- Comprovació `SentenceSyntax.block_check` (el `movable_subtree` dels blocs):
  subarbre tancat, cap dependència externa tallada, negacions dins del domini,
  cap pronom feble ni fragment protegit partit, cap referent pronominal ambigu
  quan el bloc passa al davant. Sense analitzador o amb un parse dubtós, el
  motor no proposa res.
- Els candidats ordenats de manera diferent però amb la mateixa inversió
  correcta («Encarregat el 1507 i finalitzat el 1516, el monument funerari
  d'Oddo Altoviti constitueix la primera referència itàlica») són variants
  acceptables; el test corresponent comprova la propietat (el monument és el
  subjecte de «constitueix») en lloc de l'inici literal.

### Balanç de cobertura al feix de paràgraf

- `BeamSettings.coverage_balance` (`ScoringWeights.coverage_balance`, 0,06 només
  al nivell 5 del mode profund): entre arquitectures igualment segures, la que
  reparteix la reredacció entre les frases que tenen alternatives segures
  puntua una mica més que la que la concentra en una sola frase. Es calcula
  sobre les oportunitats segures existents, mai no és una quota i mai no pot
  compensar una invalidació ni un avís gramatical. Cada alternativa exposa la
  seva distribució (`ParagraphAlternative.distribution`, `coverage_balance`).

### Puntuació de les fusions segons el ritme real de l'autor

- `style/fusion_rhythm.py`: la frase que resulta d'una fusió es valora contra
  la distribució real de longituds de l'empremta (mediana, IQR, p90: comença a
  pagar a `max(p90, mediana + dispersió)` i paga tot a `max(2·mediana, …)`), el
  nombre de clàusules, les relatives consecutives, la profunditat de
  subordinació i les comes en una sola frase. Sense empremta, val el perfil
  d'estil. És una penalització (`ritme_fusio`, component `ritme`), mai una
  invalidació: una fusió llarga competeix pitjor que una arquitectura amb millor
  ritme, i una fusió compatible amb el ritme de l'autor no paga res.

### Observabilitat de les oportunitats

- Per frase (`SentenceResult.opportunities`): `opportunities_detected`,
  `rejected_proposals`, `safe_proposals`, `structural_proposals`,
  `surface_proposals`, `unsafe_proposals`, `selected_family`,
  `selected_is_original` i un veredicte que distingeix «sense cap alternativa»,
  «cap alternativa segura», «l'original ha guanyat» i «transformada». Les
  transformacions encadenades sobre el resultat d'una altra no hi compten.
- Per paràgraf (`ParagraphResult.opportunities`): `paragraph_safe_opportunities`,
  `paragraph_structural_opportunities`, `paragraph_fusion_opportunities`,
  `paragraph_split_opportunities`, candidats del feix i distribució del canvi.
  Tot és a l'informe, a `to_dict`, a l'API local i a l'exportació.

### Opció «Llenguatge assertiu»

- Casella a la interfície (al costat de mode, nivell i empremta; desactivada per
  defecte), `--assertiu` al terminal, `assertive_language` a la configuració, a
  l'API, al resultat («Llenguatge assertiu: actiu / inactiu»), a l'historial i a
  l'exportació. Funciona amb text propi i amb esborrany LLM i és ortogonal al
  mode.
- Regles noves `resources/ca/transformations/assertiu.yaml` (només actives amb
  l'opció, família `EPISTEMIC`): reducció de la doble modalització («sembla que
  podria», «potser podria» → «podria»), hipòtesi explícita («podria
  interpretar-se com una estratègia» → «permet plantejar la hipòtesi d'una
  estratègia»), atribució directa («Com detalla X, …» → «X detalla que …»),
  limitació documental («no es pot demostrar que» → «la documentació disponible
  no permet demostrar que», només si el text parla de documentació) i
  plantejament directe («fa pensar que» → «permet plantejar que»). Regla d'or:
  més clara, mai més certa.
- `AssertiveEvaluator` (`scoring/assertive.py`): bonus petit (`assertive` 0,15)
  després de la preservació, l'epistemologia, la terminologia, la gramàtica i
  la sintaxi, per reduir redundància, fer explícita la categoria o usar el
  marcador que l'autor prefereix.
- Perfil epistemològic de l'empremta (`style/epistemic_profile.py`,
  `features.epistemic_profile`): només recomptes (densitat modal, doble
  modalització, proporció d'afirmacions directes, marcadors per categoria i
  formes preferides), amb confiança segons la mida de la mostra. Cap frase del
  corpus no es desa.

### Preservació epistemològica reforçada

- Categories explícites (`validation/categories.py`): EVIDENCE, INFERENCE,
  HYPOTHESIS, LIMITATION, UNKNOWN, declarades classe per classe a
  `epistemologia.yaml`, amb classes noves (`hypothesis`, `inference`,
  `pointer`, `documentation`, `attribution`) i marcadors explícits.
- Matriu de transicions (`validation/transitions.py`): hipòtesi → evidència,
  inferència → evidència, limitació → qualsevol cosa i afirmació → evidència
  són sempre errors; hipòtesi → inferència, evidència → inferència i afegir una
  modalització només amb una regla que ho declari; reduir una redundància només
  amb una regla `reduces_epistemic_redundancy`. Pujar de força dins d'una mateixa
  categoria («indica» → «demostra», «segons X» → «està demostrat») també és
  error. El validador epistemològic aplica la matriu a cada transformació i al
  candidat sencer; cap comparació improvisada dispersa pel codi.
- `LengthRatioValidator` accepta un marge absolut de 30 caràcters: una frase
  curta que es reformula («La documentació disponible no permet…») no queda
  invalidada per la proporció.

### Tests

- `tests/test_cobertura_i_assertiu.py`: els deu tests dels cinc canvis
  (alternativa inicial d'un connector medial, moviment d'un bloc subordinat
  intern, parser dubtós bloqueja els blocs, balanç de cobertura només entre
  oportunitats segures i mai forçat, fusió massa llarga penalitzada, fusió
  compatible amb el ritme no penalitzada, recomptes d'oportunitats), els tests
  A–F de l'opció assertiva, la matriu de transicions, el perfil epistemològic
  sense frases, el text real de deu frases (profund, nivell 5, empremta
  acadèmica, opció desactivada i activada, onze criteris) i la interfície
  (casella, API, historial, exportació, terminal).

## 1.3.2

Correcció d'arquitectura del mode profund al nivell 5, a partir d'un paràgraf
acadèmic real: el resultat continuava sent massa semblant a l'original.

- **Grau estructural real.** `TransformationFamily.structural` és una propietat
  lingüística explícita (`STRUCTURAL_FAMILIES`), no un llindar de pes. Les
  famílies lèxica, de connector, de puntuació, verbal i de reparació tenen pes
  estructural 0: tres canvis «va gaudir» → «gaudí» donen grau estructural 0 (abans
  0,9975). El grau estructural combina les aportacions (pes de la regla ×
  confiança × abast del canvi dins de la frase) com a probabilitats
  independents, amb rendiments decreixents dins d'una mateixa família: mai no
  creix linealment amb el nombre de transformacions. El grau superficial
  (`surface_degree`, dimensió `grau_superficial`) explica la resta. Una regla pot
  matisar el pes de la seva família (`structural_weight`): moure un connector és
  una reordenació lleu; «; B.» → «. B.» és una divisió lleu (`CLAUSE_SPLIT`).
- **Scoring conscient de la família.** El guany per transformacions aplica
  rendiments decreixents dins de cada família (`family_gain_decay`): repetir
  tres retocs verbals aporta poc guany addicional, i una reordenació segura pot
  superar-los en mode profund; en mode conservador no hi ha cap avantatge
  estructural. Les dimensions de preservació continuen invalidant.
- **Degradació estructural local** (`style/degradation.py`): relatives
  consecutives amb el mateix marcador («..., que fou impulsada..., que
  intensificà...»), acumulació de «que» i repetició de la mateixa estructura es
  detecten comparant candidat i original (amb el parser quan és fiable) i es
  penalitzen sense invalidar: el candidat perd el premi de reredacció i rep una
  penalització (`degradation`), rebaixada si l'empremta mostra que l'autor
  encadena subordinades.
- **Subarbres movibles.** La condició `movable_subtree` substitueix
  `single_clause` a les reordenacions de subordinades: amb anàlisi fiable, una
  subordinada complexa (amb una completiva o una relativa a dins) es mou sencera
  si és un subarbre tancat (`SentenceSyntax.closed_subtree`); sense analitzador
  val l'heurística conservadora de sempre, i un parse dubtós no autoritza mai el
  moviment. Regla nova `ordre.complement_interposat_a_inicial` (complement
  circumstancial del verb, només amb analitzador).
- **Cerca en feix d'arquitectures de paràgraf** (`pipeline/paragraph_search.py`):
  al nivell 5 del mode profund, cada frase conserva l'original, el millor
  candidat i el millor de cada signatura estructural; un feix determinista i
  acotat (`paragraph_beam_width` 6, `sentence_candidates_for_paragraph` 3)
  construeix arquitectures alternatives, aplica les regles de paràgraf al darrer
  parell de frases en el moment en què són possibles, poda conservant la
  diversitat i, sobre les arquitectures completes (sempre amb la dels guanyadors
  locals i l'original), valida contra el paràgraf original, puntua globalment
  amb l'afinitat de l'autor mesurada sobre el paràgraf sencer i tria la millor.
  Un candidat localment segon pot guanyar si dona un paràgraf millor; les frases
  queden remarcades i la traça (`ParagraphResult.search`) és accessible al
  resultat, a l'informe i a l'API local.
- **Cobertura del nivell 5.** Fusió d'un fragment nominal anafòric amb la frase
  anterior («... de la Santa Inquisició. Un fet que obligava...» → «..., un fet
  que obligava...», només amb analitzador); les divisions, reordenacions i
  fusions es comparen ara com a arquitectures de paràgraf, amb el ritme de
  l'autor.
- Una sola memòria cau del parser per a la canonada, els validadors, l'empremta
  i la degradació.
- Tests nous (`tests/test_arquitectura_paragraf.py`): famílies estructurals i no
  estructurals, rendiments decreixents, diversitat, degradació, subarbres
  movibles amb i sense parse fiable, òptim local contra global al feix,
  fragments protegits i preservació epistemològica dins del feix, i el paràgraf
  real en mode profund i conservador.

## 1.3.1

Correcció funcional i d'arquitectura del motor, a partir d'una prova real.

- `verbal.simple_a_perifrastic` només transforma amb evidència morfosintàctica
  suficient (`morphology/verbal.py`): lectures lèxiques del recurs morfològic
  (l'endevinador per sufixos no hi compta), taula d'irregulars i terminacions,
  analitzador sintàctic (categoria, forma verbal, temps, dependència i nucli) i
  pronoms febles segurs. La negació sola ja no és cap evidència: «però ja no
  sobirà» es conserva, i el motiu queda apuntat al resultat. Un predicatiu
  nominal o adjectival («ja no rei», «no independent», «no el germà») no es
  converteix mai en verb, i una partícula entre dos noms propis tampoc;
- validació per classe de transformació (`validation/verbal.py`): un canvi
  verbal ha de partir d'un verb de passat i produir un infinitiu que existeixi,
  segons el recurs morfològic local; LanguageTool és una capa addicional, no
  l'única garantia;
- famílies sintàctiques generals guiades pel parser: subordinades adverbials
  (interposada ↔ inicial ↔ final), causals («X perquè Y» ↔ «Com que Y, X»),
  connectors (medial ↔ inicial), relatives copulatives ↔ aposicions,
  impersonals («es considera» ↔ «hom considera») i fusió copulativa («no és
  només A. És B.» → «no és només A, sinó també B.»). Les condicions
  estructurals (`is_subject`, `is_adverbial_clause`, `mood`, `no_clitic`,
  `single_clause`, `is_apposition`, `no_subject`) comproven l'arbre de
  dependències quan hi ha analitzador i recorren a les heurístiques sense;
- els verbs conjugats de les condicions de patró (`has_finite_verb`) es
  reconeixen amb l'analitzador quan es refia de la frase: les divisions i
  puntuacions ja s'apliquen a text real;
- signatura estructural de cada candidat (`ORIGINAL`, `CONNECTOR`, `REORDER`,
  `CLAUSE_SPLIT`, `COPULAR_MERGE`, `MULTI_TRANSFORM(...)`), deduplicació de
  candidats gairebé idèntics i selecció que conserva la diversitat de famílies;
- puntuació del mode profund: grau de reredacció estructural per família (un
  canvi sintàctic pesa més que un connector, i un canvi entre frases més que un
  de dins de la frase), escalat per la gramaticalitat i sense compensar mai cap
  error de preservació; en mode conservador no compta;
- observabilitat: família, signatura, grau estructural i evidència de cada
  transformació al resultat, a l'informe i a l'API local;
- test de regressió amb el text real i amb els casos d'ambigüitat el·líptica.

## 1.3.0

- mode de xarxa local (`parafrasi-cat web --lan`), opcional i mai per defecte;
- ús amb dos Chromebooks: un executa el motor, l'altre només obre Chrome;
- autenticació temporal amb codi d'accés de sis xifres i sessió amb testimoni
  aleatori (`HttpOnly`, `SameSite=Strict`), exigida a totes les rutes de l'API
  en aquest mode;
- comprovació de `Host` adaptada: adreces IP privades sí, dominis d'Internet
  mai, en tots dos modes; també s'accepten les adreces del contenidor de
  ChromeOS (`100.115.92.x`, `penguin.linux.test`), que no són registrables;
- límit d'intents del codi d'accés: passats deu errors seguits, el servidor
  deixa d'acceptar codis durant un minut, de manera que provar les sis xifres
  una per una deixa de ser viable;
- interfície remota sobre LAN: la mateixa aplicació, sense cap segona UI;
- documentació de Crostini i de quina adreça IP cal fer servir
  (`docs/chromebook-dual.md`) i llançador `start_parafrasi_lan.sh`;
- privacitat descrita amb precisió: el text no va a Internet, i en mode de
  xarxa local circula dins de la LAN entre el navegador i el servidor;
- mateixa qualitat lingüística que el mode local, comprovada amb un test de
  paritat entre els dos modes;
- registre local i fitxers de preferències i d'empremta segurs amb dos
  dispositius alhora: escriptura atòmica i lectura amb pany;
- càrrega del parser segura amb dues peticions alhora: la segona espera el
  model en comptes de veure'l com a no disponible;
- una canonada construïda amb els pesos vells ja no es queda a la memòria si
  mentrestant s'ha desat una valoració o una empremta;
- una petició refusada (403 d'amfitrió o 401 de sessió) ja no desbarata la
  petició següent de la mateixa connexió;
- l'estat dels recursos lingüístics es comprova després d'arrencar el
  servidor, que així contesta de seguida.

## 1.2.0

L'empremta d'autor respon «com escriu?» i no només «quines paraules fa
servir?». Esquema de l'empremta 1.1, compatible amb les empremtes antigues.

- `rhythm_profile`: longitud de frase en tokens lingüístics (mitjana, mediana,
  desviació, coeficient de variació, percentils), franges curta / mitjana /
  llarga amb llindars derivats del corpus, matriu de transició, trigrames,
  ratxes, correlació de retard 1, canvi absolut mitjà i paràgrafs.
- `syntactic_profile`, calculat amb el parser local (que només analitza):
  coordinació per tipus i mida, subordinació per tipus i profunditat, ordre
  del subjecte i dels complements, distància de dependències, complexitat i
  patrons abstractes de frase. Cap frase del corpus no es guarda.
- Suficiència de mostra explícita: `sample_size` i `confidence` (`low`,
  `medium`, `high`) a cada secció; una mètrica poc fiable no puntua.
- Puntuació: components `ritme` i `sintaxi` dins de l'afinitat amb l'autor
  (`rhythm_similarity_score`, `syntactic_similarity_score`), amb explicacions
  per candidat; pes reduït amb text propi i complet amb esborranys LLM; sempre
  per sota dels invariants.
- Web: secció «Estructura i ritme» en triar una empremta, amb la matriu de
  transició en paraules i «Veure detalls».
- TextDescriptives avaluada i descartada (dependències pesants per a mètriques
  trivials); tot s'implementa internament.

## 1.1.0

- selector d'origen del text: text propi (per defecte, comportament de sempre)
  o esborrany generat amb LLM;
- adaptació autoral per a esborranys generats amb LLM, basada només en
  l'empremta real de l'autor: sense LLM, sense generació neuronal, sense cap
  detector d'IA;
- scoring de similitud amb l'empremta (`afinitat_autor`): longitud i ritme de
  les frases, sobreús i familiaritat de connectors, puntuació, estabilitat
  terminològica i construccions, amb explicació per candidat i sempre per sota
  dels invariants factuals, epistemològics i gramaticals;
- protecció contra contaminació del corpus: un text marcat com a esborrany no
  pot entrar mai a cap empremta, i el feedback registra d'on venia el text;
- manteniment del funcionament offline i determinista.

També endureix el motor davant de les limitacions conegudes de la 1.0. No hi
ha cap regla nova ni cap ampliació de cobertura: el que canvia és què
s'autoritza i com s'explica el que no.

### Errors nous contra errors de l'original

- Els avisos de LanguageTool es classifiquen en quatre gravetats
  (`BLOCKING`, `STRONG_PENALTY`, `WARNING`, `INFORMATIONAL`) segons si són nous
  i si cauen dins del fragment transformat, amb un mot de marge.
- Un problema que ja hi havia al text original ja no penalitza cap candidat, de
  manera que un nom propi que LanguageTool marca com a error d'ortografia no
  descarta la reescriptura.
- Un error gramatical nou dins del canvi invalida el candidat i el motiu diu
  quina regla l'ha introduït; el mateix error lluny del canvi només penalitza.
- Els avisos de validació porten pes: una penalització forta compta el triple
  que un advertiment d'estil.

### Confiança sintàctica

- Criteri explícit de fiabilitat de cada arbre: una sola arrel, sense cicles ni
  dependències fora de la frase, amb verb conjugat, amb nucli predicatiu, sense
  relacions sense classificar i sense contradiccions amb la morfologia local.
- Una frase que no el supera baixa a nivell 2: cap transformació estructural
  sobre text fragmentari.
- Els resultats porten notes en català que expliquen per què una frase no s'ha
  transformat, o per què s'ha limitat.
- Memòria cau d'anàlisis per sessió, només en memòria, que no afecta el
  determinisme.

### Concordança

- Validador local de concordança de subjecte i verb amb el parser: només
  compten les discordances que ha introduït el motor, i els subjectes
  col·lectius en queden fora expressament.
- Reparació determinista amb la morfologia local quan la forma correcta és
  única, registrada com una transformació explícita `concordanca.reparacio`.
  Amb més d'una forma possible, o cap, el candidat es descarta.

### Nivell 5 i longitud de frase

- Abans de fusionar dues frases es calcula la longitud resultant i es compara
  amb el màxim de l'autor, la distribució de la seva empremta o la longitud que
  ha declarat preferir; mana la més restrictiva.
- Amb un autor de frase curta la fusió no es proposa i el motiu queda al
  resultat; amb un autor de períodes llargs continua disponible.
- La fusió tampoc no s'aplica si el parser no es refia de cap de les dues
  frases.

### Recursos i interfície

- Mode lingüístic complet i mode bàsic, dits explícitament a la interfície,
  amb botó per instal·lar els recursos que falten.
- Nou `scripts/install_morphology.py`: baixa el diccionari de Softcatalà i en
  genera el recurs local, amb informació i confirmació prèvies.

## 1.0.0

Primera versió completa. `parafrasi-cat` reredacta text en català amb regles
explícites, recursos locals i selecció determinista de candidats. No hi ha cap
LLM ni cap servei generatiu, i un cop instal·lats els recursos tot funciona
sense connexió.

### Motor de regles

- 40 regles declaratives en 13 famílies (lèxic, connectors, verbal,
  nominalització, còpula, agent, presència, ordre, temporals, subordinades,
  fusió, divisió i puntuació), cadascuna amb exemples positius i negatius que
  els tests verifiquen.
- Motor de patrons sobre tokens amb retrocés, condicions declaratives,
  excepcions i plantilles amb filtres.
- Generació de candidats amb combinacions compatibles i reaplicació de regles,
  deduplicació i límit de canvi.
- Nivells 1 a 5: lèxic, connectors, sintaxi, entre frases i reestructuració de
  paràgraf. El nivell 5 activa una fase de paràgraf que el 4 no té.
- Modes conservador i de reredacció profunda, que fixen risc, confiança,
  combinacions i nivell màxim sense tocar mai cap protecció.

### Preservació del contingut

- Detecció de fragments intocables: noms propis, dates, xifres, números romans,
  citacions, text entre cometes i terminologia protegida.
- Validació de cada candidat: invariants factuals, terminologia, negacions,
  atenuació i certesa, classificació epistemològica explícita, gramaticalitat
  heurística i marge de longitud.
- Cap error de preservació no és negociable: invalida el candidat.

### Català

- Segmentació, tokenització, clítics, apòstrofs, guionets i numerals romans.
- Lexicó de classes tancades i endevinador morfològic per sufixos.

### Morfologia

- Importació reproduïble del diccionari de Softcatalà (`catalan-dict-tools`,
  GPL-2.0+/LGPL-2.1+) amb `scripts/import_softcatala.py`: 1.188.611 formes amb
  lema, categoria, gènere, nombre, persona, temps i mode.
- Les regles conjuguen amb la morfologia en lloc de parelles escrites a mà, amb
  els mapatges antics com a reserva.

### Sintaxi

- Analitzador sintàctic català local amb spaCy i `ca_core_news_sm` (UD Catalan
  AnCora): dependències, subjecte, objecte, subordinades i coordinacions.
- El parser **només analitza**: no genera text ni pren cap decisió.
- Condicions de regla opt-in que consulten lema, categoria, gènere, nombre,
  persona, dependència i rol sintàctic. Les regles que no les demanen no
  canvien de comportament.

### LanguageTool

- Adaptador local que arrenca el servidor de LanguageTool una sola vegada i el
  reutilitza, amb comprovació d'estat, reinici si cau i tancament net.
- Memòria cau de validació per sessió, només en memòria.
- Només valida: no genera, no reescriu i no aplica cap correcció.
- Opcional: sense Java o sense LanguageTool, el motor continua amb els
  validadors interns.

### Estil, diccionaris i preferències

- Empremta estilística de l'autor a partir del seu corpus, amb estadístics
  robustos i sense entrenar cap model. Es pot crear des de la interfície.
- Diccionaris terminològics per projecte, combinables, amb termes protegits.
- Preferències explícites de l'autor i feedback manual com a recomptes
  inspeccionables, amb una jerarquia de prioritats documentada.

### Interfície

- Interfície web local, sense consola i sense cap recurs extern.
- Estat dels recursos lingüístics i instal·lació amb confirmació explícita.
- Càrrega de fitxers `.txt` i `.md`, creació d'empremtes, tria d'estil,
  diccionaris, preferències, nivell i mode.
- Candidats amb diferències, regles, puntuacions i advertiments; marcatge de
  candidats; edició manual; còpia i exportació.
- Registre de traçabilitat local, opcional i desactivat per defecte.
- Llançadors per a Windows, macOS i Linux.

### Fora de línia

- Cap component consulta Internet durant l'ús. Les úniques descàrregues són les
  d'instal·lació, sempre amb confirmació i des d'scripts fora del paquet.
- Els tests comproven que durant una sessió normal no s'obre cap connexió que
  no sigui amb aquest mateix ordinador.

### Llicència

- Codi propi sota GPL-3.0-or-later, compatible amb tots els components amb què
  el programa s'executa. Atribucions a `THIRD_PARTY_LICENSES.md`.
