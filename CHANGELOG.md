# Registre de canvis

El format segueix [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/) i el
projecte utilitza [versionatge semàntic](https://semver.org/lang/ca/).

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
