#!/bin/bash
# =============================================================
#  depaneurIA — Script d'installation automatique
#  Système : Linux openSUSE
#  Usage   : bash setup.sh
# =============================================================

set -e  # Arrête le script si une erreur survient

# Couleurs pour les messages
VERT="\e[32m"
JAUNE="\e[33m"
ROUGE="\e[31m"
BLEU="\e[34m"
RESET="\e[0m"

ok()   { echo -e "${VERT}✓ $1${RESET}"; }
info() { echo -e "${BLEU}→ $1${RESET}"; }
warn() { echo -e "${JAUNE}⚠ $1${RESET}"; }
err()  { echo -e "${ROUGE}✗ ERREUR : $1${RESET}"; exit 1; }

echo ""
echo -e "${BLEU}╔════════════════════════════════════════╗${RESET}"
echo -e "${BLEU}║     depaneurIA — Installation          ║${RESET}"
echo -e "${BLEU}╚════════════════════════════════════════╝${RESET}"
echo ""

# ─── ÉTAPE 1 : Vérifier Git ────────────────────────────────
info "Étape 1/6 — Vérification de Git..."
if ! command -v git &>/dev/null; then
  info "Installation de Git via zypper..."
  sudo zypper install -y git || err "Impossible d'installer Git"
fi
ok "Git $(git --version | awk '{print $3}') installé"

# ─── ÉTAPE 2 : Installer Node.js via NVM ───────────────────
info "Étape 2/6 — Installation de Node.js via NVM..."
export NVM_DIR="$HOME/.nvm"

if [ ! -d "$NVM_DIR" ]; then
  info "Téléchargement de NVM..."
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  ok "NVM installé"
else
  ok "NVM déjà installé"
fi

# Charger NVM dans le script actuel
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Installer Node 22 LTS
info "Installation de Node.js 22 LTS..."
nvm install 22
nvm use 22
nvm alias default 22
ok "Node.js $(node --version) installé"

# Ajouter NVM au .bashrc si pas déjà là
if ! grep -q 'NVM_DIR' ~/.bashrc; then
  echo '' >> ~/.bashrc
  echo 'export NVM_DIR="$HOME/.nvm"' >> ~/.bashrc
  echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> ~/.bashrc
  ok "NVM ajouté au démarrage du terminal"
fi

# ─── ÉTAPE 3 : Installer pnpm ──────────────────────────────
info "Étape 3/6 — Installation de pnpm..."
if ! command -v pnpm &>/dev/null; then
  npm install -g pnpm@9
  ok "pnpm installé"
else
  ok "pnpm $(pnpm --version) déjà installé"
fi

# ─── ÉTAPE 4 : Cloner ou mettre à jour le projet ───────────
info "Étape 4/6 — Récupération du projet depuis GitHub..."
PROJET_DIR="$HOME/depaneurIA"

if [ -d "$PROJET_DIR" ]; then
  info "Le dossier existe déjà — mise à jour..."
  cd "$PROJET_DIR"
  git pull origin main
  ok "Projet mis à jour"
else
  info "Clonage du repo..."
  git clone https://github.com/Topbrutus/depaneurIA.git "$PROJET_DIR"
  ok "Projet cloné dans $PROJET_DIR"
fi

cd "$PROJET_DIR"

# ─── ÉTAPE 5 : Fichier .env ────────────────────────────────
info "Étape 5/6 — Configuration des variables d'environnement..."
if [ ! -f .env ]; then
  cp .env.example .env
  ok "Fichier .env créé — vous pourrez y mettre vos clés plus tard"
else
  ok "Fichier .env déjà présent"
fi

# ─── ÉTAPE 6 : Installer les dépendances ───────────────────
info "Étape 6/6 — Installation des dépendances (peut prendre 1-2 min)..."
pnpm install
ok "Toutes les dépendances installées"

# ─── RÉSUMÉ ────────────────────────────────────────────────
echo ""
echo -e "${VERT}╔════════════════════════════════════════╗${RESET}"
echo -e "${VERT}║   ✓ Installation terminée !            ║${RESET}"
echo -e "${VERT}╚════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Votre projet est dans : ${BLEU}$PROJET_DIR${RESET}"
echo ""
echo -e "  ${JAUNE}Prochaine étape :${RESET}"
echo -e "  1. Ouvrez VS Code dans le projet :"
echo -e "     ${BLEU}code $PROJET_DIR${RESET}"
echo ""
echo -e "  2. Pour lancer le site plus tard :"
echo -e "     ${BLEU}cd $PROJET_DIR && pnpm dev${RESET}"
echo ""
echo -e "  ${VERT}Bonne construction ! 🚀${RESET}"
echo ""
