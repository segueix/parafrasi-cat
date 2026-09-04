# Recursos lingüístics

`parafrasi-cat` funciona sense cap recurs extern. Dos components **opcionals**
en milloren la qualitat, i tots dos s'executen en local. Les llicències i les
atribucions són a [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

| Component | Aporta | Sense ell |
|---|---|---|
| Morfologia de Softcatalà | Lema, categoria, gènere, nombre, persona, temps i mode d'1,19 milions de formes | S'utilitza l'analitzador intern: lexicó de classes tancades i endevinador per sufixos |
| Parser sintàctic (spaCy) | Dependències, subjecte, objecte, subordinades i coordinacions | S'utilitzen les heurístiques de sintagmes actuals |
| LanguageTool local | Validació de gramàtica, concordança i puntuació de cada candidat | S'utilitzen els validadors interns del motor |

Cap dels dos es versiona en aquest repositori, per llicència en el primer cas i
per mida en el segon. Un cop instal·lats, tot funciona fora de línia.

## Morfologia de Softcatalà

### Importació

```bash
python scripts/install_morphology.py            # informa, demana confirmació i ho fa tot
python scripts/install_morphology.py --info     # només informa
```

O des de la interfície: **Recursos lingüístics → Instal·la la morfologia
catalana**. En tots dos casos es mostra origen, versió, mida, llicència i
atribució abans de baixar res.

Si preferiu fer-ho pas a pas, o ja teniu el repositori:

```bash
git clone --depth 1 https://github.com/Softcatala/catalan-dict-tools
python scripts/import_softcatala.py --source catalan-dict-tools
```

L'script llegeix `resultats/lt/diccionari.txt`, que té una línia per forma:

```
presenten presentar VMIP3P00
sarcòfags sarcòfag NCMP000
```

L'etiqueta és del joc EAGLES/PAROLE per al català. L'importador la converteix
als trets del motor i desa el resultat en una base SQLite indexada a
`resources/ca/morphology/generated/catala.sqlite`, amb un fitxer de metadades
al costat que registra l'origen, el commit, la data i la llicència.

### Què s'importa i què no

| Categoria | Entrades | S'importa |
|---|---|---|
| Verbs | 877.142 | Sí |
| Noms comuns | 186.465 | Sí |
| Adjectius | 120.402 | Sí |
| Adverbis | 4.602 | Sí |
| Noms propis | 99.704 | **No** |

Els noms propis queden fora a propòsit: el motor els protegeix i no els
flexiona mai. El resultat són 1.188.611 formes i uns 120 MB, que s'importen en
uns segons. No cal expandir cap llista de milions de formes: la base indexada
respon per forma i per lema sense carregar res a memòria.

### Lectura de l'etiqueta

```
V  M  I  P  3  S  0  0
│  │  │  │  │  │  │  └─ variant: 0 general, V valencià, B balear…
│  │  │  │  │  │  └──── gènere (participis)
│  │  │  │  │  └─────── nombre
│  │  │  │  └────────── persona
│  │  │  └───────────── temps
│  │  └──────────────── mode
│  └─────────────────── tipus de verb
└────────────────────── categoria
```

Quan una forma té variants, mana sempre la general: el diccionari conté
`constitueix` (VMIP3S0**0**) i `constituïx` (VMIP3S0**V**), i el motor tria la
primera.

### Què hi guanya el motor

Les regles ja no porten parelles escrites a mà. On abans hi havia

```yaml
transformation: "{cop|map(és=constitueix,són=constitueixen)} {pred}"
```

ara hi ha

```yaml
transformation: "{cop|inflect(constituir,és=constitueix,són=constitueixen)} {pred}"
```

El filtre `inflect` analitza la forma trobada, en pren els trets i conjuga el
lema d'arribada. La prioritat és explícita:

1. **recurs morfològic fiable** — conjuga el lema amb els trets reals;
2. **mapatge explícit** — els parells que la regla declara, com a reserva;
3. **heurística** — l'endevinador per sufixos de l'analitzador intern;
4. **no transformar** — si res no és fiable, la regla no proposa res.

Els parells de reserva es conserven a propòsit: sense el recurs importat, el
motor es comporta exactament com abans.

## Parser sintàctic català

### Per què spaCy

Es van comparar les opcions disponibles per al català:

| | spaCy `ca_core_news_sm` | Stanza |
|---|---|---|
| Dependències, morfologia i lemes | Sí | Sí |
| Dependències obligatòries | 19 paquets, cap de PyTorch | Inclou `torch` i `requests` |
| Mida al disc | 28 MB | Centenars de MB amb PyTorch |
| Velocitat | ~6 ms per frase, CPU | Més lent en CPU |
| Llicència | Codi MIT, model GPL-3.0 | Codi Apache-2.0, models variables |

Per a una eina d'escriptori local que ha de funcionar en un ordinador
qualsevol i sense connexió, spaCy és clarament la millor opció: analitza tot el
que el motor necessita amb una fracció de la mida i sense arrossegar PyTorch.

### Instal·lació

```bash
python scripts/install_parser.py          # informa i demana confirmació
python scripts/install_parser.py --info   # només informa
```

O des de la interfície, a **Recursos lingüístics**.

### Què aporta i què no

El parser **només analitza**. No genera text, no completa frases, no reescriu i
no decideix estil. La generació continua sent exclusivament de les regles, els
diccionaris i la selecció determinista de candidats.

Aporta: arrel de la frase, subjecte, objecte, complements, subordinades,
coordinacions, negacions i els trets morfològics de cada mot.

### Ús a les regles: opt-in

Una regla només consulta el parser si declara un bloc `syntax`:

```yaml
conditions:
  syntax:
    requires_parser: true      # sense parser, la regla no s'aplica
    subject_number: pl         # el subjecte principal ha de ser plural
    no_clause_boundary: true   # l'encaix no pot partir una subordinada
    max_clauses: 1
    no_negation: true
```

Les regles que no el declaren **no canvien de comportament**, ni amb parser ni
sense. La jerarquia és:

```
morfologia local  +  parser sintàctic local  +  heurístiques  +  regles explícites
```

Quan el parser té prou confiança, s'utilitza la informació sintàctica. Quan no
en té, o quan no està instal·lat, actuen les heurístiques de sempre. Si el
parser i els invariants de seguretat es contradiuen, **manen els invariants i
no es transforma**.

### Criteri de confiança

«Prou confiança» no és una impressió: és un criteri explícit
(`syntax.assess_confidence`) que cada arbre ha de superar.

| Criteri | Per què |
|---|---|
| Hi ha mots analitzats | sense anàlisi no hi ha res a dir |
| Exactament una arrel | dues arrels són dos fragments enganxats |
| Cap dependència fora de la frase ni cap cicle | l'arbre ha de ser coherent |
| Almenys un verb conjugat | sense verb és un fragment nominal |
| El nucli és un verb o un predicat amb còpula | si no, l'estructura és nominal |
| Cap relació sense classificar | el parser mateix reconeix que no ho sap |
| La morfologia local no el contradiu en el nombre | sintaxi i morfologia han de dir el mateix |

L'últim criteri només s'aplica al subjecte i al nucli, i només si el recurs
morfològic està instal·lat: comparar-ho tot dispararia falses alarmes amb les
formes ambigües.

Quan una frase no supera el criteri, **no es força cap anàlisi**: el nivell
efectiu d'aquella frase baixa a 2 (lèxic i connectors), les regles estructurals
no s'hi apliquen i el resultat en diu el motiu. En una oració completa amb el
mateix contingut, en canvi, les regles de nivell 3 sí que actuen.

### Concordança: detecció i reparació

Amb el parser instal·lat, cada candidat passa pel validador `concordanca`, que
compara el nombre del subjecte principal amb el del seu verb. Dues regles el
fan prudent:

- **Només compten les discordances noves.** Les que ja eren al text de l'autor
  no descarten res i tampoc no s'esmenen: el motor no corregeix l'original.
- **Els subjectes col·lectius queden fora.** «La majoria dels autors accepten»
  i «el conjunt de làpides mostra» són tots dos correctes; la llista de nuclis
  col·lectius és tancada i revisable, no s'endevina.

Si la discordança és del motor i el recurs morfològic dona **una sola** forma
possible, `candidates.repair` la corregeix i la deixa registrada com una
transformació més:

```
concordanca.reparacio: «presenta» → «presenten»
  Concordança: «prova.plural» ha deixat «presenta» sense concordar amb
  «sarcòfags» (pl); la morfologia local només admet «presenten»
```

Amb més d'una forma possible, o cap, no s'inventa res: el candidat es descarta.
Tampoc no es repara res dins del fragment que ha escrit una regla —allà la
forma correcta és responsabilitat de la regla— ni amb LanguageTool, que no
reescriu mai.

## LanguageTool local

### Instal·lació

```bash
python scripts/install_languagetool.py          # informa i demana confirmació
python scripts/install_languagetool.py --info   # només informa
```

O des de la interfície: **Recursos lingüístics → Instal·la la validació
avançada de català**, que ensenya component, origen, mida i llicència abans de
baixar res i espera una confirmació explícita.

L'script és **fora del paquet** a propòsit: és l'única peça del projecte que
accedeix a Internet, i ho fa una sola vegada. El paquet `parafrasi_cat` no
importa cap client de xarxa, i un test ho comprova.

### Ús

```bash
parafrasi-cat rewrite text.txt --languagetool    # si s'ha activat a la configuració
```

o marcant **Validació avançada de català** a la interfície. Està desactivada
per defecte: el motor no depèn ni de Java ni de LanguageTool.

### Què pot fer i què no

LanguageTool **només valida**. No genera la paràfrasi, no reescriu el text, no
decideix el contingut i no aplica cap correcció. El flux és:

```
motor de regles → candidat → LanguageTool local → problemes? → puntuació o descart → selector
```

### Errors nous contra errors de l'original

El motor compara els problemes de l'original amb els del candidat i classifica
cada problema **nou** segons on cau respecte del fragment transformat (amb un
mot de marge a cada banda):

| Gravetat | Quan | Efecte |
|---|---|---|
| `BLOCKING` | error gramatical nou dins del canvi (`CONCORDANCES_*`, `DIACRITICS`, `PREPOSITIONS`, `issueType: grammar`…) | invalida el candidat |
| `STRONG_PENALTY` | el mateix error lluny del canvi, o puntuació, majúscules i ortografia dins del canvi | pesa el triple que un advertiment |
| `WARNING` | estil, repeticions, preferències, qüestions discutibles | baixa la puntuació |
| `INFORMATIONAL` | el problema ja hi era, o no implica incorrecció | cap efecte |

La distinció importa perquè LanguageTool marca com a error d'ortografia molts
noms propis legítims («Oddo Altoviti», «Rovezzano»). Si el motor no els ha
escrit, no han empitjorat res i no poden descartar la reescriptura sencera.
A l'inrevés, «Els sarcòfags presenta dos cranis» sortint d'una regla que ha
tocat el subjecte sí que la descarta, i l'informe diu quina regla ha estat.

Les regles catalanes de concordança sovint arriben amb `issueType:
uncategorized`, però amb la categoria `CONCORDANCES_*`. El motor mira totes
dues coses.

Una discordança amb el verb lluny del canvi pot escapar-se d'aquest criteri de
proximitat: la recull el validador de concordança del parser, que no depèn de
la distància. Són dues capes, i cadascuna cobreix el que a l'altra se li escapa.

### Servidor persistent

L'adaptador arrenca el servidor local de LanguageTool **una sola vegada** per
sessió i el reutilitza per a totes les reescriptures. Aporta:

- arrencada mandrosa: no es paga fins que es demana la primera validació;
- comprovació d'estat abans de cada petició;
- reinici automàtic si el procés cau;
- tancament net en sortir, sense deixar cap procés Java orfe;
- memòria cau per sessió amb clau (text, configuració, llengua), només en
  memòria i mai a disc, que no afecta el determinisme.

La comunicació és **exclusivament de bucle local**: l'adaptador comprova
l'adreça abans de connectar-s'hi i no té cap manera d'apuntar a un servei
remot. Mai no es fa servir l'API de languagetool.org.

Mesures en un ordinador de proves: arrencada del servidor 2,1 s; primera
comprovació 4,4 s (LanguageTool hi carrega el model català); comprovacions
repetides, immediates per la memòria cau.

## Estat dels recursos

Segons el que hi hagi instal·lat, el motor treballa en **mode lingüístic
complet** (morfologia, parser i LanguageTool) o en **mode bàsic** (només els
components interns: menys cobertura i més prudència). La interfície ho diu en
una línia i, si falta algun recurs, hi posa el botó per instal·lar-lo.

```
Mode lingüístic complet actiu

Morfologia catalana      ✓ activa
Parser sintàctic català  ✓ activa
LanguageTool local       ✓ actiu
Java                     ✓ disponible
Mode fora de línia       ✓ disponible
```

Des de Python:

```python
from parafrasi_cat.adapters import resources_status
print(resources_status(".").summary())
```
