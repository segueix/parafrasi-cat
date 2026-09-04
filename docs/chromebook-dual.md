# Parafrasi-cat amb dos Chromebooks

Un Chromebook executa el motor; l'altre només obre la interfície amb Chrome.
La qualitat lingüística és exactament la mateixa que treballant directament al
Chromebook servidor: el mode de xarxa local només canvia per on viatja el
text, no què fa el motor amb ell.

```
CHROMEBOOK 1 (servidor)              CHROMEBOOK 2 (client)
ChromeOS + Linux                     Chrome, i res més
  parafrasi-cat                        obre http://IP-DEL-1:8765
  Python + spaCy                       escriu el codi d'accés
  morfologia + LanguageTool            fa servir la interfície de sempre
        │                                        ▲
        └──────────── Wi-Fi de casa ─────────────┘
```

El Chromebook 2 **no necessita** Linux, Python, Java, spaCy, LanguageTool,
la morfologia de Softcatalà ni Git. Tots els recursos viuen només al
Chromebook 1, que és qui executa morfologia → parser → regles → puntuació →
LanguageTool i retorna el resultat al navegador.

## Chromebook 1 — el servidor

1. **Activeu el Linux de ChromeOS**: Configuració → Avançat → Desenvolupadors
   → Entorn de desenvolupament de Linux → Activa.
2. **Instal·leu parafrasi-cat** dins del terminal de Linux:

   ```bash
   git clone https://github.com/segueix/parafrasi-cat
   cd parafrasi-cat
   python3 -m pip install -e .
   ```

3. **Instal·leu els recursos lingüístics** (una sola vegada, amb connexió):

   ```bash
   python3 scripts/install_morphology.py     # diccionari de Softcatalà
   python3 scripts/install_parser.py         # spaCy + model català
   python3 scripts/install_languagetool.py   # LanguageTool (cal Java)
   ```

   També es poden instal·lar més tard des de la mateixa interfície.

4. **Engegueu-lo en mode de xarxa local**:

   ```bash
   parafrasi-cat web --lan
   ```

   o feu doble clic a `start_parafrasi_lan.sh`. Veureu una cosa així:

   ```
   Parafrasi-cat
   Mode: Xarxa local
   Port: 8765
   Autenticació: activa
   Motor: actiu
   Recursos lingüístics: s'estan comprovant

   Codi d'accés: 583214
   ```

   El codi es genera a cada arrencada, no es desa enlloc i no s'envia enlloc.

   Al cap d'uns segons hi surten tres línies més (`LanguageTool`, `Parser` i
   `Morfologia`). Comprovar el parser vol dir carregar-ne el model, i per això
   es fa a part: el servidor ja contesta mentre es fa, i la interfície també
   n'ensenya l'estat.

5. **Activeu la redirecció del port**, si cal (vegeu la secció següent).
6. **Deixeu el Chromebook 1 encès** i amb la sessió oberta mentre treballeu.
7. **Manteniu-lo a la mateixa Wi-Fi** que el Chromebook 2.

## La redirecció de ports de ChromeOS (Crostini)

El Linux de ChromeOS s'executa dins d'un contenidor amb la seva pròpia adreça
IP (sovint `100.115.92.x`). **Aquesta no és l'adreça que ha de fer servir el
Chromebook 2.** Perquè el port sigui visible des de fora del contenidor:

Configuració → Avançat → Desenvolupadors → Entorn de desenvolupament de Linux
→ **Redirecció de ports** → afegiu el port `8765` (TCP).

Després, comproveu-ho per ordre; cada pas descarta una causa:

1. **Al Chromebook 1, dins del navegador de ChromeOS** (no el de Linux), obriu
   `http://localhost:8765`. Si surt la pantalla del codi d'accés, la
   redirecció del contenidor cap a ChromeOS funciona.
2. **Al Chromebook 2**, obriu `http://ADREÇA-IP-DEL-CHROMEBOOK-1:8765`. Si el
   pas 1 funcionava i aquest no, el que falla és l'accés des de la xarxa, no
   parafrasi-cat.

Si el pas 2 no funciona en la vostra versió de ChromeOS, és una limitació de
la redirecció de ports del sistema i queda fora del que pot fer aquest
projecte: parafrasi-cat ja escolta a totes les interfícies de la màquina Linux
(`0.0.0.0`).

## L'adreça IP: la del Chromebook, no la del contenidor

Parafrasi-cat **no mostra cap adreça IP** perquè no pot saber quina és
accessible des de la resta de la xarxa: el procés viu dins del contenidor i hi
veu la seva pròpia, que no serveix.

L'adreça bona és la de la Wi-Fi del Chromebook 1:

Configuració → Xarxa → Wi-Fi → la xarxa connectada → **Adreça IP**.

Sol tenir la forma `192.168.x.x` o `10.x.x.x`. Si el que veieu comença per
`100.115.92.`, és la del contenidor Linux: no és aquesta.

## Chromebook 2 — el client

1. Obriu Chrome i aneu a `http://ADREÇA-IP-DEL-CHROMEBOOK-1:8765`.
2. Escriviu el codi d'accés de sis xifres que surt al Chromebook 1.
3. Ja hi sou: és la mateixa interfície, amb tot el que té —text, origen del
   text, mode, nivell, empremta, estructura i ritme, diccionaris,
   preferències, recursos, candidats, puntuacions, feedback i exportació.

Detalls del funcionament des del client:

- **Fitxers**: quan trieu un `.txt` o un `.md`, el llegeix el navegador del
  Chromebook 2 i n'envia el contingut al servidor. El servidor no toca mai el
  sistema de fitxers del Chromebook 2.
- **Exportació**: la descàrrega es desa al Chromebook 2, com qualsevol altra
  descàrrega de Chrome.
- **Empremtes d'autor**: els textos viatgen al Chromebook 1, que els analitza
  i hi desa l'empremta. No s'envien a Internet i no es desen al client.
- **Historial**: continua desactivat per defecte; si l'activeu, s'escriu al
  Chromebook 1.
- **Instal·lar recursos**: el botó de la interfície executa l'instal·lador al
  Chromebook 1, amb la confirmació explícita de sempre.

## Seguretat

- El mode de xarxa local és **opcional**. Sense `--lan`, el servidor només
  escolta a `127.0.0.1` i no demana res, com sempre.
- Amb `--lan` cal un **codi d'accés** de sis xifres generat amb un generador
  criptogràfic a cada arrencada. Quan és correcte, el servidor obre una
  **sessió** amb un testimoni aleatori en una galeta `HttpOnly`,
  `SameSite=Strict`, que caduca sola i desapareix en aturar el servidor.
- **Totes** les rutes de l'API exigeixen sessió en aquest mode, també des del
  Chromebook 1. Els fitxers estàtics (la pàgina, el CSS i el JavaScript) són
  els mateixos que es distribueixen amb el paquet i no contenen res privat.
- Passats **deu codis erronis seguits**, el servidor deixa d'acceptar codis
  durant un minut, i tampoc no accepta el bo. Sense aquest límit, un milió de
  combinacions de sis xifres es proven en menys d'una hora. El comptador és de
  tot el servidor i no de cada dispositiu, perquè a la xarxa local qualsevol es
  pot canviar l'adreça.
- La capçalera `Host` es continua comprovant: s'accepten aquesta màquina, les
  adreces IP privades de la xarxa local i les del contenidor de ChromeOS
  (`100.115.92.x`, `penguin.linux.test`), mai un domini d'Internet. Això barra
  la reassignació de noms (*DNS rebinding*): els noms que s'accepten són sota
  dominis reservats, que ningú no pot registrar.
- Amb `--pin CODI` podeu fixar un codi per no haver-lo de tornar a escriure a
  cada arrencada. No es desa enlloc; és vostra la decisió.

## Privacitat

Parafrasi-cat no envia text a serveis d'Internet. En mode local, el text no
surt del dispositiu. En mode de xarxa local, només circula entre el navegador
client i el servidor Parafrasi-cat dins de la LAN.

Concretament, el text **no** va mai a GitHub, Softcatalà, languagetool.org,
spaCy ni cap altre servidor d'Internet. El programa tampoc no obre ports al
router, no fa servir UPnP, ni túnels, ni ngrok, ni Cloudflare Tunnel, ni
Tailscale, ni cap servei extern: només accepta connexions entrants dins de la
xarxa local.

**Utilitzeu aquesta funció només en una xarxa Wi-Fi privada i de confiança.**
La connexió dins de la xarxa local és HTTP i no va xifrada: qui tingui accés a
la mateixa xarxa podria veure el text que hi circula. En una Wi-Fi pública o
compartida, feu servir el mode local.

## HTTPS a la xarxa local: per què no hi és

S'ha estudiat afegir `--lan-https` amb un certificat generat automàticament, i
s'ha decidit **no implementar-ho**:

- La biblioteca estàndard de Python no genera certificats. Caldria afegir la
  dependència `cryptography` o cridar l'ordre `openssl`, i el projecte no en
  té cap de les dues.
- Un certificat autofirmat per a una adreça IP privada no el pot validar cap
  navegador. A ChromeOS, el Chromebook 2 veuria un avís de seguretat a cada
  sessió, que caldria acceptar a mà; l'alternativa és instal·lar una autoritat
  certificadora pròpia a cada dispositiu, que ja és un projecte de PKI.
- L'experiència resultant seria pitjor i la sensació de seguretat, enganyosa.

Per això el mode de xarxa local és HTTP, l'avís de xarxa de confiança és
explícit i la galeta de sessió no porta l'atribut `Secure`. Si un dia
convingués, seria una funcionalitat a part.

## Actualitzar

Manualment, al Chromebook 1:

```bash
cd parafrasi-cat
git pull
python3 -m pip install -e .
```

El programa no actualitza res sol.
