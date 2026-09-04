# Eines externes opcionals i llicències

`parafrasi-cat` no depèn de cap eina externa: el nucli funciona només amb
Python i PyYAML. Les eines següents poden millorar l'anàlisi lingüística,
sempre com a **adaptadors opcionals**, executats localment, desactivats per
defecte i sense enviar mai text a cap servidor.

## Ja integrades

| Eina | Estat | Documentació |
|---|---|---|
| Diccionari de Softcatalà (`catalan-dict-tools`) | **Integrat** com a proveïdor morfològic opcional. Doble GPL-2.0+/LGPL-2.1+, commit `138828448433`. El recurs el genera l'usuari amb `scripts/import_softcatala.py` i no es versiona. | [`recursos-linguistics.md`](recursos-linguistics.md) |
| LanguageTool | **Integrat** com a validador local opcional. LGPL-2.1+, versió provada 6.6. Servidor local persistent; mai l'API remota. Cal Java. | [`recursos-linguistics.md`](recursos-linguistics.md) |
| spaCy i `ca_core_news_sm` | **Integrat** com a analitzador sintàctic local opcional. Codi MIT, model GPL-3.0 (UD Catalan AnCora). Només analitza; no és generatiu. | [`recursos-linguistics.md`](recursos-linguistics.md) |

Les llicències verificades i l'atribució són a
[`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

## Encara no integrades

Abans d'integrar-ne cap, cal revisar-ne la llicència i deixar-ne constància
en aquest document. Les dades següents són orientatives: **comproveu sempre
la llicència de la versió concreta** que vulgueu fer servir.

| Eina | Què aporta | Llicència (orientativa) | Consideracions |
|---|---|---|---|
| [Apertium](https://www.apertium.org/) (apertium-cat) | Analitzador i generador morfològic, tokenització, desambiguació superficial | Motor i dades lingüístiques: GPL-2.0 o posterior | Copyleft fort: un adaptador que l'invoqui com a procés extern evita problemes d'enllaç; distribuir-lo integrat obliga a GPL. |
| [FreeLing](https://nlp.lsi.upc.edu/freeling/) | Anàlisi morfològica, etiquetatge, reconeixement d'entitats, anàlisi sintàctica per al català | AGPL-3.0 (hi ha llicència comercial) | Copyleft molt fort (inclou ús en xarxa). Executar-lo com a procés local separat és l'opció més segura. |
| [Stanza](https://stanfordnlp.github.io/stanza/) | Tokenització, lematització, etiquetatge i anàlisi de dependències per al català | Codi: Apache-2.0; models: variables | Descartat a favor de spaCy: arrossega PyTorch com a dependència obligatòria i ocupa centenars de megabytes per a la mateixa funció. |
| Diccionaris de Softcatalà: sinònims i tesaurus | Sinònims | Tesaurus: LGPL-3.0+/GPL-3.0+ | Encara no s'utilitzen. La part morfològica sí que està integrada (vegeu més amunt). |

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
