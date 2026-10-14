#!/data/data/com.termux/files/usr/bin/bash
# Lancement de l'agent Dolibarr Sysinfo sous Termux.
# Usage: ./run.sh [--loop]
set -e
cd "$(dirname "$0")"
pkg list-installed python 2>/dev/null | grep -q python || {
    echo "Installation de Python (Termux)..."
    pkg install -y python
}
python -m pip install -q -r requirements.txt
exec python run.py --config config.json "$@"
