# Registre de canvis

El format segueix [Keep a Changelog](https://keepachangelog.com/ca/1.1.0/) i el
projecte utilitza [versionatge semàntic](https://semver.org/lang/ca/).

## 1.0.0

Primera versió completa. `parafrasi-cat` reredacta text en català amb regles
explícites, recursos locals i selecció determinista de candidats. No hi ha cap
LLM ni cap servei generatiu, i un cop instal·lats els recursos tot funciona
sense connexió.

### Motor de regles

- 40 regles declaratives en 13 famílies (lèxic, connectors, verbal,
  nominalització, còpula, agent, presència, ordre, temporals, subordinades,
  fusió, divisió i puntuació), cadascuna amb exemples positius i negatius que
  els tests verifiquen.
- Motor de patrons sobre tokens amb retrocés, condicions declaratives,
  excepcions i plantilles amb filtres.
- Generació de candidats amb combinacions compatibles i reaplicació de regles,
  deduplicació i límit de canvi.
- Nivells 1 a 5: lèxic, connectors, sintaxi, entre frases i reestructuració de
  paràgraf. El nivell 5 activa una fase de paràgraf que el 4 no té.
- Modes conservador i de reredacció profunda, que fixen risc, confiança,
  combinacions i nivell màxim sense tocar mai cap protecció.

### Preservació del contingut

- Detecció de fragments intocables: noms propis, dates, xifres, números romans,
  citacions, text entre cometes i terminologia protegida.
- Validació de cada candidat: invariants factuals, terminologia, negacions,
  atenuació i certesa, classificació epistemològica explícita, gramaticalitat
  heurística i marge de longitud.
- Cap error de preservació no és negociable: invalida el candidat.

### Català

- Segmentació, tokenització, clítics, apòstrofs, guionets i numerals romans.
- Lexicó de classes tancades i endevinador morfològic per sufixos.

### Morfologia

- Importació reproduïble del diccionari de Softcatalà (`catalan-dict-tools`,
  GPL-2.0+/LGPL-2.1+) amb `scripts/import_softcatala.py`: 1.188.611 formes amb
  lema, categoria, gènere, nombre, persona, temps i mode.
- Les regles conjuguen amb la morfologia en lloc de parelles escrites a mà, amb
  els mapatges antics com a reserva.

### Sintaxi

- Analitzador sintàctic català local amb spaCy i `ca_core_news_sm` (UD Catalan
  AnCora): dependències, subjecte, objecte, subordinades i coordinacions.
- El parser **només analitza**: no genera text ni pren cap decisió.
- Condicions de regla opt-in que consulten lema, categoria, gènere, nombre,
  persona, dependència i rol sintàctic. Les regles que no les demanen no
  canvien de comportament.

### LanguageTool

- Adaptador local que arrenca el servidor de LanguageTool una sola vegada i el
  reutilitza, amb comprovació d'estat, reinici si cau i tancament net.
- Memòria cau de validació per sessió, només en memòria.
- Només valida: no genera, no reescriu i no aplica cap correcció.
- Opcional: sense Java o sense LanguageTool, el motor continua amb els
  validadors interns.

### Estil, diccionaris i preferències

- Empremta estilística de l'autor a partir del seu corpus, amb estadístics
  robustos i sense entrenar cap model. Es pot crear des de la interfície.
- Diccionaris terminològics per projecte, combinables, amb termes protegits.
- Preferències explícites de l'autor i feedback manual com a recomptes
  inspeccionables, amb una jerarquia de prioritats documentada.

### Interfície

- Interfície web local, sense consola i sense cap recurs extern.
- Estat dels recursos lingüístics i instal·lació amb confirmació explícita.
- Càrrega de fitxers `.txt` i `.md`, creació d'empremtes, tria d'estil,
  diccionaris, preferències, nivell i mode.
- Candidats amb diferències, regles, puntuacions i advertiments; marcatge de
  candidats; edició manual; còpia i exportació.
- Registre de traçabilitat local, opcional i desactivat per defecte.
- Llançadors per a Windows, macOS i Linux.

### Fora de línia

- Cap component consulta Internet durant l'ús. Les úniques descàrregues són les
  d'instal·lació, sempre amb confirmació i des d'scripts fora del paquet.
- Els tests comproven que durant una sessió normal no s'obre cap connexió que
  no sigui amb aquest mateix ordinador.

### Llicència

- Codi propi sota GPL-3.0-or-later, compatible amb tots els components amb què
  el programa s'executa. Atribucions a `THIRD_PARTY_LICENSES.md`.
