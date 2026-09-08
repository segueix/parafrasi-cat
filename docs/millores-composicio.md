# Composició: cobertura i comprovació dels resultats

## Canvis

- La regla de «Però» absorbeix la coma opcional abans d'introduir «Tanmateix,».
- Les comes duplicades introduïdes per una transformació bloquegen el candidat,
  també si hi ha espais entre elles. Un defecte ja present a l'original no es
  penalitza de nou.
- El moviment de circumstancials no pot separar «com» d'una construcció com
  «Com es pot observar», encara que el parser l'etiqueti com a adverbi.
- Dues regles noves mouen aquest incís complet al final o després del subjecte.
  La segona exigeix un subjecte verificat pel parser. Són patrons delimitats,
  no un reordenador universal.
- La composició mostra «Per què hi ha aquestes alternatives?»: regles provades
  en la frase inicial, regles amb propostes, candidats conservats, descartats,
  límits de cerca i motius de rebuig. Reutilitza la traça existent; no repeteix
  la cerca. Una regla sense proposta no identifica per si sola quina condició
  interna ha fallat.

## Mesura reproduïble

```bash
python scripts/benchmark_composicio.py
# Amb LanguageTool local instal·lat:
python scripts/benchmark_composicio.py --languagetool
```

Es pot passar un corpus JSON propi amb `--corpus fitxer.json` (llista de frases).
Per comparar versions, cal usar el mateix corpus i els mateixos recursos locals.

Comparació local de les sis frases comunicades, sense parser disponible i amb
LanguageTool desactivat. Base del motor: `67ec306`; els canvis intermedis de
colors, sinònims manuals i reserva de selecció no amplien les regles mesurades.

| Mesura | Abans | Després |
|---|---:|---:|
| Frases amb almenys una alternativa | 4/6 | 4/6 |
| Frases amb candidats de reordenació | 0/6 | 1/6 |
| Candidats acceptats amb comes duplicades | 6 | 0 |

La cobertura de reordenació augmenta **16,67 punts percentuals** en aquesta
mostra. S'eliminen els sis candidats amb aquest defecte de puntuació; això no
significa un 100 % de correcció global. Les frases 3 i 4 continuen sense
alternatives en aquest entorn. La mostra és petita, ha guiat les correccions i
no és una avaluació independent de generalització. L'etiqueta REORDER mesura
la traça d'una operació, no equivalència semàntica demostrada.

## Recursos següents, sense models generatius

Prioritzar un corpus de parelles revisades (original i reformulacions
acceptables), patrons per construcció, informació de règim i complements
verbals, i antecedents inequívocs de relatives. Cada ampliació ha de portar
exemples negatius i una avaluació sobre frases reservades que no hagin guiat
la implementació. Ampliar sinònims, per si sol, no amplia la reestructuració.

No hi ha dades per prometre un percentatge general de millora amb aquests
recursos. Cal mesurar separadament cobertura, correcció gramatical, preservació
del sentit i naturalitat, amb revisió humana de les dues últimes.
