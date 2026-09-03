# Corpus d'exemple per a l'anàlisi estilomètrica

Tres corpus artificials petits, escrits expressament amb estils
deliberadament diferents, per comprovar que `parafrasi-cat style build` i
`parafrasi-cat style compare` els distingeixen. Cada corpus té un directori
principal (quatre textos) i un de validació (dos textos del mateix estil).

| Corpus | Tret principal |
|---|---|
| `concis/` | Frases curtes, poques comes, «és», «fet per», «acabat», «hi ha», passat perifràstic, primera persona del singular. |
| `academic/` | Frases llargues, punt i coma, «constitueix», «obra de», «finalitzat», «presenta», passat simple, impersonals i passives, sense primera persona. |
| `narratiu/` | Frases mitjanes, guions i exclamacions, primera persona del plural, «realitzat per», «apareix», «en canvi», «ja que». |

Els textos són inventats (llocs, dates i noms ficticis) i no procedeixen de
cap autor real.

```
parafrasi-cat style build corpus/exemples/concis --validation corpus/exemples/concis-validacio -o /tmp/concis.json
parafrasi-cat style build corpus/exemples/academic -o /tmp/academic.json
parafrasi-cat style compare /tmp/concis.json /tmp/academic.json
```
