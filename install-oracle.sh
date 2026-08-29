#!/bin/bash
# ---------------------------------------------------------------------------
# Installation de DO DISPLAY NOTIFIER en surveillance continue (Oracle Cloud
# ou n'importe quelle machine Ubuntu allumée en permanence).
#
# Usage :
#   curl -fsSL https://raw.githubusercontent.com/Docci91/one-piece-notifier/main/install-oracle.sh -o install.sh
#   chmod +x install.sh
#   ./install.sh
#
# Le script va te demander ton topic ntfy et (optionnel) ton webhook Discord,
# puis installer et démarrer un service qui tourne en continu, redémarre
# automatiquement en cas de plantage, et se relance tout seul si le serveur
# reboote.
# ---------------------------------------------------------------------------

set -e

REPO_URL="https://github.com/Docci91/one-piece-notifier.git"
INSTALL_DIR="$HOME/one-piece-notifier"
SERVICE_NAME="one-piece-notifier"

echo "== DO DISPLAY NOTIFIER - installation en surveillance continue =="
echo ""

# 1. Dépendances système
echo "-> Installation des dépendances système..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git

# 2. Récupération du code
if [ -d "$INSTALL_DIR" ]; then
  echo "-> Dossier existant trouvé, mise à jour..."
  cd "$INSTALL_DIR"
  git pull
else
  echo "-> Clonage du dépôt..."
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# 3. Dépendances Python
echo "-> Installation des dépendances Python..."
pip3 install --break-system-packages -q requests beautifulsoup4

# 4. Configuration
echo ""
read -p "Ton identifiant ntfy (NTFY_TOPIC) : " NTFY_TOPIC_VALUE
read -p "URL du webhook Discord (laisser vide si non utilisé) : " DISCORD_WEBHOOK_URL_VALUE

# 5. Service systemd (tourne en continu, redémarre seul si crash ou reboot)
echo "-> Création du service systemd..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=DO Display Notifier - surveillance continue
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment=NTFY_TOPIC=$NTFY_TOPIC_VALUE
Environment=DISCORD_WEBHOOK_URL=$DISCORD_WEBHOOK_URL_VALUE
ExecStart=/usr/bin/python3 $INSTALL_DIR/monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "== Installation terminée =="
echo "Le service tourne en continu. Commandes utiles :"
echo "  Voir les logs en direct :  sudo journalctl -u $SERVICE_NAME -f"
echo "  Statut :                    sudo systemctl status $SERVICE_NAME"
echo "  Arrêter :                   sudo systemctl stop $SERVICE_NAME"
echo "  Redémarrer :                sudo systemctl restart $SERVICE_NAME"
