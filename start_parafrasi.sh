#!/usr/bin/env bash
# Obre parafrasi-cat en un navegador. No cal escriure cap ordre.
# Ús: feu doble clic sobre aquest fitxer, o executeu-lo des del terminal.
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "No s'ha trobat Python. Instal·leu Python 3.11 o superior des de https://python.org"
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

echo "Obrint parafrasi-cat al navegador…"
echo "Per aturar-lo, tanqueu aquesta finestra o premeu Ctrl+C."
exec "$PYTHON" -m parafrasi_cat web
