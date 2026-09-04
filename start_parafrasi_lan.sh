#!/usr/bin/env bash
# Obre parafrasi-cat perquè també s'hi pugui entrar des d'un altre dispositiu
# de la mateixa xarxa Wi-Fi (per exemple, un segon Chromebook amb Chrome).
#
# Aquest ordinador executa el motor; l'altre només hi obre la interfície.
# El codi d'accés surt en aquesta finestra i canvia a cada arrencada.
#
# Ús: feu doble clic sobre aquest fitxer, o executeu-lo des del terminal.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PARAFRASI_CAT_PORT:-8765}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "No s'ha trobat Python. Instal·leu Python 3.11 o superior."
  echo "A ChromeOS: Configuració → Avançat → Desenvolupadors → Entorn de desenvolupament de Linux."
  read -r -p "Premeu Retorn per tancar." _
  exit 1
fi

if ! "$PYTHON" -c "import parafrasi_cat" >/dev/null 2>&1; then
  echo "Instal·lant parafrasi-cat per primera vegada…"
  "$PYTHON" -m pip install -e . || {
    echo "La instal·lació ha fallat."
    read -r -p "Premeu Retorn per tancar." _
    exit 1
  }
fi

cat <<'AVIS'
────────────────────────────────────────────────────────────────
 PARAFRASI-CAT — MODE XARXA LOCAL

 En aquest ordinador s'hi executa tot el motor lingüístic.
 L'altre dispositiu només necessita un navegador.

 Al segon dispositiu, obriu:

     http://ADREÇA-IP-D-AQUEST-ORDINADOR:PORT

 L'adreça IP de Wi-Fi la trobareu a la configuració del sistema.
 A ChromeOS: Configuració → Xarxa → Wi-Fi → la xarxa connectada.
 No feu servir la IP del contenidor Linux: no és la mateixa.

 Si feu servir el Linux de ChromeOS (Crostini), potser caldrà
 activar la redirecció del port a Configuració → Avançat →
 Desenvolupadors → Linux → Redirecció de ports.

 Utilitzeu-ho només en una xarxa Wi-Fi privada i de confiança.
────────────────────────────────────────────────────────────────
AVIS
echo " Port: ${PORT}"
echo
echo "Per aturar-ho, tanqueu aquesta finestra o premeu Ctrl+C."
echo

exec "$PYTHON" -m parafrasi_cat web --lan --port "$PORT" --no-browser
