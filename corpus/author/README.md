# Corpus de l'autor

Textos propis de l'autor, en fitxers `.txt` o `.md` (UTF-8). Serveixen per
construir l'empremta estilística de l'autor:

```
parafrasi-cat style build corpus/author/                      # → style/author.json
parafrasi-cat style build corpus/author/ --validation corpus/validacio-autor/ --profile resources/style/autor.yaml
```

Un fitxer `exclosos.txt` dins d'aquest directori pot llistar noms o patrons
de fitxers que no s'han d'analitzar (un per línia). L'empremta resultant no
conté el corpus, només recomptes i fragments curts; vegeu `style/README.md`.

Aquest directori està exclòs del control de versions (vegeu `.gitignore`):
els textos de l'autor són privats i no s'han de publicar.
