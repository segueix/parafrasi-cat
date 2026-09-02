# Eines externes opcionals i llicències

`parafrasi-cat` no depèn de cap eina externa: el nucli funciona només amb
Python i PyYAML. Les eines següents podrien millorar l'anàlisi lingüística
en fases posteriors, sempre com a **adaptadors opcionals**, executats
localment, desactivats per defecte i sense enviar mai text a cap servidor.

Abans d'integrar-ne cap, cal revisar-ne la llicència i deixar-ne constància
en aquest document. Les dades següents són orientatives: **comproveu sempre
la llicència de la versió concreta** que vulgueu fer servir.

| Eina | Què aporta | Llicència (orientativa) | Consideracions |
|---|---|---|---|
| [Apertium](https://www.apertium.org/) (apertium-cat) | Analitzador i generador morfològic, tokenització, desambiguació superficial | Motor i dades lingüístiques: GPL-2.0 o posterior | Copyleft fort: un adaptador que l'invoqui com a procés extern evita problemes d'enllaç; distribuir-lo integrat obliga a GPL. |
| [FreeLing](https://nlp.lsi.upc.edu/freeling/) | Anàlisi morfològica, etiquetatge, reconeixement d'entitats, anàlisi sintàctica per al català | AGPL-3.0 (hi ha llicència comercial) | Copyleft molt fort (inclou ús en xarxa). Executar-lo com a procés local separat és l'opció més segura. |
| [LanguageTool](https://languagetool.org/) | Correcció gramatical i d'estil amb regles per al català (mantingudes per Softcatalà) | LGPL-2.1 o posterior | Cal Java. Es pot executar com a servidor **local**; no s'ha de fer servir mai el servei en línia des d'aquest projecte. |
| [Stanza](https://stanfordnlp.github.io/stanza/) | Tokenització, lematització, etiquetatge i anàlisi de dependències neuronals per al català | Codi: Apache-2.0; models: consulteu la llicència de cada model i dels treebanks d'origen | És un model neuronal **d'anàlisi**, no generatiu. Requereix PyTorch i descarregar models (només un cop). Contradiu l'objectiu de mantenir el motor lleuger; només com a adaptador experimental. |
| [spaCy](https://spacy.io/) (models `ca_core_news_*`) | Anàlisi similar a Stanza | Codi: MIT; models: consulteu la llicència de cada model | Mateixes consideracions que Stanza. |
| Diccionaris de Softcatalà (Hunspell, sinònims) | Ortografia, formes flexionades, sinònims | Diverses (GPL/LGPL segons el recurs) | Útils per generar `resources/ca/lexicon/` amb scripts reproduïbles. Cal respectar-ne l'atribució. |

## Condicions per integrar una eina

1. S'ha d'implementar com a adaptador d'un protocol existent (`Analyzer`,
   `MorphologyProvider`) en un mòdul separat, p. ex. `parafrasi_cat/adapters/`.
2. Ha de ser una dependència opcional (`pip install parafrasi-cat[apertium]`),
   mai obligatòria.
3. Ha d'executar-se íntegrament a l'ordinador de l'usuari.
4. La seva absència no pot trencar el motor: el `RuleBasedAnalyzer` sempre és
   la solució de recanvi.
5. Cal documentar-ne la llicència, la versió provada i la manera d'instal·lar-la.
6. No es pot copiar codi d'aquestes eines al projecte; només invocar-les.

## El que queda explícitament fora

- LLM i models generatius de qualsevol mida (locals o remots).
- API generatives i serveis de traducció o redacció en línia.
- Qualsevol component que enviï el text de l'usuari fora de l'ordinador.
- Telemetria, comptadors d'ús o descàrregues silencioses.
