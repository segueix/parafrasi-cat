# Recursos lingüístics

`parafrasi-cat` funciona sense cap recurs extern. Dos components **opcionals**
en milloren la qualitat, i tots dos s'executen en local. Les llicències i les
atribucions són a [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

| Component | Aporta | Sense ell |
|---|---|---|
| Morfologia de Softcatalà | Lema, categoria, gènere, nombre, persona, temps i mode d'1,19 milions de formes | S'utilitza l'analitzador intern: lexicó de classes tancades i endevinador per sufixos |
| LanguageTool local | Validació de gramàtica, concordança i puntuació de cada candidat | S'utilitzen els validadors interns del motor |

Cap dels dos es versiona en aquest repositori, per llicència en el primer cas i
per mida en el segon. Un cop instal·lats, tot funciona fora de línia.

## Morfologia de Softcatalà

### Importació

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

Un problema de concordança, gramàtica o ortografia invalida el candidat; la
resta el penalitzen. Els problemes que ja hi havia al text original no compten,
igual que fa el validador gramatical intern.

Les regles catalanes de concordança sovint arriben amb `issueType:
uncategorized`, però amb la categoria `CONCORDANCES_*`. El motor mira totes
dues coses, de manera que «Aquests sarcòfags presenta dos cranis» queda
descartat i «Aquest sarcòfag presenta dos cranis» no.

### Comunicació

L'adaptador executa LanguageTool com un procés a part que llegeix el text per
l'entrada estàndard. No s'obre cap connexió, ni tan sols a l'amfitrió local, i
no es fa servir mai l'API de languagetool.org. Tots els candidats d'una
reescriptura es comproven amb una sola execució.

## Estat dels recursos

La interfície mostra l'estat de cada component:

```
Morfologia catalana: [activa]  1188611 formes del diccionari de Softcatalà.
LanguageTool local:  [actiu]   La validació avançada està activa i s'executa en aquest ordinador.
Java:                [disponible]
```

Des de Python:

```python
from parafrasi_cat.adapters import resources_status
print(resources_status(".").summary())
```
