# Llicències de tercers

`parafrasi-cat` no distribueix cap dada ni cap binari de tercers. Els recursos
lingüístics opcionals els obté cada usuari al seu ordinador, i aquest fitxer
documenta d'on surten, amb quina llicència i amb quina atribució.

## Softcatalà — catalan-dict-tools

| | |
|---|---|
| Origen | https://github.com/Softcatala/catalan-dict-tools |
| Commit verificat | `138828448433a110958a85778522c2eaa246d769` (2026-09-03) |
| Llicència | Doble: **GPL-2.0-or-later** i **LGPL-2.1-or-later** |
| Fitxer utilitzat | `resultats/lt/diccionari.txt` |
| Ús | Morfologia catalana (lema, categoria, gènere, nombre, persona, temps, mode) |

Atribució, tal com consta a `fdic-to-hunspell/dades/copyright.txt` del repositori
original:

> Corrector ortogràfic català. Fitxer d'afixos i llista de paraules.
> Copyright (C) 2013- Jaume Ortolà <jaumeortola@gmail.com>
> Copyright (C) 2002-2008 Joan Moratinos <jmo@softcatala.org>

Fonts que el diccionari mateix declara: Diccionari de l'Institut d'Estudis
Catalans (1996 i 2007), Diccionari Català/Castellà de Francesc de B. Moll,
Diccionari d'Ispell d'Ignasi Labastida, Recull de gentilicis de M.M. Ramon i
C. Rigo, Diccionari Ortogràfic i de Pronúncia del Valencià (AVL), Diccionari
Normatiu Valencià (AVL), ésAdir (CCMA) i Termcat.

**Aquest repositori no conté cap dada derivada del diccionari.** El recurs
local el genera `scripts/import_softcatala.py` i està a `.gitignore`. El motiu
és de llicència: les dades són copyleft i la llicència de `parafrasi-cat`
encara no està definida, de manera que distribuir-ne un derivat comprometria
una decisió que correspon al propietari del projecte.

Si algun dia es vol distribuir el recurs generat, cal fer-ho sota GPL-2.0+ o
LGPL-2.1+, amb aquesta atribució i amb el text de la llicència.

## LanguageTool

| | |
|---|---|
| Origen | https://github.com/languagetool-org/languagetool i https://languagetool.org |
| Versió provada | **6.6** (2025-03-27) |
| Llicència del nucli | **LGPL-2.1-or-later** (`COPYING.txt` del repositori) |
| Ús | Validació local de gramàtica, concordança i puntuació |
| Requisit | Java |

El diccionari de categories gramaticals català de LanguageTool prové del mateix
lloc. Ho diu el fitxer
`languagetool-language-modules/ca/src/main/resources/org/languagetool/resource/ca/README.txt`:

> The Catalan part-of-speech dictionary was created by Jaume Ortolà based on
> Softcatalà dictionaries, released under a dual license LGPL v2.1 and GPL v2.
> See: https://github.com/Softcatala/catalan-dict-tools

**Aquest repositori no conté LanguageTool.** L'instal·la
`scripts/install_languagetool.py`, amb confirmació explícita, a `vendor/`, que
està a `.gitignore`. Mai no es fa servir l'API de languagetool.org: el programa
s'executa com un procés local.

## Dependència de Python

| Paquet | Llicència |
|---|---|
| PyYAML | MIT |

És l'única dependència del projecte. Tota la resta és biblioteca estàndard.
