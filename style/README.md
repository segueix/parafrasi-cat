# Empremtes estilístiques

Aquest directori conté les empremtes estilístiques (`<autor>.json`) que
genera l'anàlisi estilomètrica del corpus d'un autor, i l'esquema JSON que
les descriu (`fingerprint.schema.json`).

```
parafrasi-cat style build corpus/author/            # → style/author.json
parafrasi-cat style build corpus/author/ --validation corpus/validacio/ --exclude "esborrany*"
parafrasi-cat style compare style/author.json style/altre.json
parafrasi-cat style show style/author.json
```

L'empremta és un JSON explícit, llegible i editable, pensat per
versionar-se amb Git: no conté el corpus (només fragments curts com a
exemples) i es genera de manera determinista (mateix corpus i mateixos
recursos → mateix fitxer). Cada característica guarda el valor, el nombre
d'observacions, la confiança, la variabilitat entre documents i alguns
exemples. Els estadístics són robustos (mediana, desviació absoluta
mediana, pesos per document limitats) perquè cap text excepcional domini el
perfil.

Un perfil d'estil (`resources/style/<nom>.yaml`) pot referenciar una
empremta amb la clau `fingerprint: style/<autor>.json`; aleshores el motor
consulta les preferències de l'autor (variants equivalents, connectors,
densitat de comes) en puntuar els candidats.

Les llistes i els paràmetres de l'anàlisi són a `resources/ca/style/`.
