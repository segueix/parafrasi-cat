# parafrasi-cat

Motor **local** de reredacció i parafraseig en català, amb una interfície web
que s'executa al mateix ordinador.

> **El motor no utilitza LLM ni serveis generatius. La reredacció es produeix
> mitjançant regles lingüístiques explícites, recursos locals, anàlisi
> morfològica i sintàctica, validació gramatical i selecció determinista de
> candidats.**

**Versió 1.0.0.** Un cop instal·lats els recursos, tot funciona sense connexió i
cap text no surt mai de l'ordinador.

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
```

El servidor es lliga a l'amfitrió local i la pàgina no carrega cap recurs
extern.

## Com instal·lar els recursos

La interfície té una secció **Recursos lingüístics** amb l'estat de cada
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
python scripts/install_parser.py                                  # spaCy + model català
python scripts/install_languagetool.py                            # LanguageTool (cal Java)
git clone --depth 1 https://github.com/Softcatala/catalan-dict-tools
python scripts/import_softcatala.py --source catalan-dict-tools   # morfologia
```

Cap dels tres és obligatori: sense ells, el motor funciona amb els seus
components interns.

## Com crear una empremta d'autor

A la secció **Empremta de l'autor**: poseu-hi un nom, trieu els vostres textos
`.txt` o `.md` i premeu **Crea l'empremta**. L'anàlisi es fa en aquest
ordinador, els textos no en surten i **no s'entrena cap model**: només se'n
desen recomptes i estadístics robustos a `style/<nom>.json`.

També des del terminal:

```bash
parafrasi-cat style build corpus/author/ --profile resources/style/autor.yaml
parafrasi-cat style show style/autor.json
```

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
| 3 | Sintaxi: còpula, agent, presència, ordre, temporals, subordinades | 26 |
| 4 | Entre frases: divisió i puntuació | 3 |
| 5 | **Reestructuració controlada de paràgraf** | 1 |

El **nivell 5 és diferent del 4**: activa una fase de paràgraf que reorganitza
frases senceres (fusió amb represa anafòrica). El nivell 4 treballa dins de
cada frase i no arriba a aquesta fase. Les proteccions són exactament les
mateixes als dos nivells.

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

## LanguageTool

Comprova gramàtica, concordança i puntuació de cada candidat. **Només valida**:
no genera la paràfrasi, no reescriu el text i no aplica cap correcció. El motor
de candidats és qui decideix si un candidat es penalitza o es descarta.

El servidor local s'arrenca **una sola vegada** per sessió i es reutilitza, amb
comprovació d'estat, reinici si cau i tancament net. Mai no es fa servir l'API
de languagetool.org.

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

## Fora de línia

Cap component consulta Internet durant el parafraseig, l'anàlisi, la validació,
la puntuació, la selecció, el feedback o l'exportació. Les úniques connexions
possibles són amb aquest mateix ordinador: el navegador amb la interfície, i la
interfície amb el servidor local de LanguageTool. Els tests ho comproven
bloquejant tota connexió que no sigui de bucle local.

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
- **Sense LanguageTool no es comprova la concordança de la sortida.** El
  validador intern detecta contraccions incorrectes, signes desaparellats i
  defectes de puntuació, però no concordança ni règim verbal.
- **La primera comprovació amb LanguageTool és lenta** (uns segons), perquè el
  servidor local hi carrega el model català. Les següents són immediates.

## Llicència

GPL-3.0-or-later. Vegeu [`LICENSE`](LICENSE) i, per a les atribucions de cada
component, [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

Documentació addicional: [`docs/recursos-linguistics.md`](docs/recursos-linguistics.md),
[`docs/arquitectura.md`](docs/arquitectura.md),
[`docs/principis-de-preservacio.md`](docs/principis-de-preservacio.md),
[`CHANGELOG.md`](CHANGELOG.md).
