# Corpus per ampliar i comprovar regles locals

L'importador utilitza únicament la biblioteca estàndard de Python. La xarxa
només s'utilitza amb `--download`; el motor de reredacció no consulta aquests
serveis ni carrega corpus sense revisar. Les versions estan fixades a
`sources.json` i cada importació conserva la llicència, l'atribució i el SHA-256.

```bash
python scripts/import_paraphrases.py --dataset parafraseja --split train --download
python scripts/import_paraphrases.py --dataset paws-ca --split validation --download
python scripts/import_paraphrases.py --dataset ancora --split train --download
```

També s'accepta `--source fitxer` per importar sense xarxa. Els fitxers locals
s'identifiquen com a versió no verificada, amb la seva empremta SHA-256.
Les dades importades són a `generated/`, exclòs de Git. Parafraseja declara
CC BY-NC-ND 4.0: les dades transformades no es publiquen amb aquest repositori.
PAWS-ca i la versió fixada d'UD Catalan-AnCora declaren CC BY 4.0. Es manté
l'atribució als fitxers generats. No es baixa ni s'executa codi dels corpus.

## Etiquetes amb significat explícit

| Camp | Significat |
|---|---|
| `source_label_raw` / `source_labels_raw` | Etiquetes originals, sense esborrar contradiccions entre duplicats. |
| `source_label` | `equivalent`, `non_equivalent`, `unknown` o `conflict`, segons la font. No és un veredicte del motor. |
| `review_status` | `pending` o `reviewed`. Importar no constitueix una revisió. |
| `risk_flags` | Canvis de xifres, romans, quantificadors, negacions o etiquetes contradictòries que s'han de comprovar. No demostren per si sols un error. |
| `rule_evidence_eligible` | Només cert per a una parella revisada com a equivalent, sense avisos i de la partició `train`. No activa cap regla. |
| `observed_not_validated_rule` | Patró de dependències observat a AnCora; no és una transformació ni una paràfrasi. |

Els filtres són conservadors: «23» → «vint-i-tres» també pot generar un avís.
No detecten totes les alteracions de persones, relacions, abast o significat.
Les particions `validation` i `test` es reserven per avaluar; no es promouen
com a exemples per elaborar regles.

## Revisió versionable

Prepareu un JSONL de revisions amb una línia per parella:

```json
{"id":"SHA256_DE_LA_PARELLA","reviewer":"Dani","verdict":"equivalent","note":"Conserva subjecte, dades, negació i significat."}
```

Els altres veredictes són `non_equivalent` i `uncertain`. La revisió requereix
responsable i justificació; l'identificador depèn dels dos textos i de la font.

```bash
python scripts/import_paraphrases.py --dataset parafraseja --split train --source recursos.jsonl --reviews revisions.jsonl
```

Després cal formular la regla amb condicions, exemples propis positius i
negatius i proves sobre frases no utilitzades per construir-la. No es generen
regles executables automàticament a partir de l'etiqueta del corpus.

## Primera aplicació

La inspecció de parelles de reordenació ha orientat dues regles declaratives:
`ordre.concessio_nominal_inicial_a_final` i
`ordre.concessio_nominal_final_a_inicial`. Mouen «tot i / malgrat + grup
nominal» entre els extrems d'una oració simple, amb coma explícita. No mouen
«tot i que + oració», relatives ni frases amb incisos addicionals. Els exemples
versionats són propis; no es redistribueixen frases del corpus.

A la interfície, «filtres automàtics superats» substitueix la garantia aparent
«validada»; els textos modificats manualment deixen de presentar-se com a
originals intactes. L'usuari encara ha de comprovar el sentit dels sinònims.
