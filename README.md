# NinoScreen — Multi-Site Dashboard

Application Python / PySide6 / Qt Widgets / Qt WebEngine conçue pour garder plusieurs services web visibles et utilisables dans un même cockpit.

L’état actuel du projet utilise **36 tuiles web** réparties sur **3 pages de 12 tuiles**, avec une grille **3 × 4 par page**.

## Fonctionnalités principales

- 36 tuiles web indépendantes
- 3 pages × 12 tuiles
- chargement d’URL par tuile avec normalisation
- navigation indépendante : retour, avancer, recharger
- zoom indépendant par tuile
- profil Qt WebEngine partagé pour cookies/cache/sessions web
- mode focus
- mode Split avec deux tuiles côte à côte
- restauration du focus et de la disposition logique
- page RUN / Corvo séparée
- persistance des URL, zooms, page courante, focus, plein écran et taille de fenêtre
- **autosauvegarde débouncée pendant que l’application reste ouverte**
- sauvegarde finale lors de la fermeture
- miniatures et état des tuiles en mode focus

## Dépendances

- Python 3.11+ ; Python 3.12 validé sur le VPS Château Astra
- `PySide6==6.6.3.1`
- `keyring>=25.0`

`PySide6 6.6.3.1` est volontairement épinglé : cette version a été validée sur le CPU virtuel du VPS Château Astra, alors qu’une version PySide6 plus récente testée pendant le déploiement exigeait des extensions CPU non exposées par ce serveur.

## Installation

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

### Linux / macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

## Sessions web

NinoScreen utilise actuellement **un profil WebEngine partagé entre les 36 tuiles**. Les cookies et sessions web vivent donc dans le profil du navigateur, tandis que le fichier de session NinoScreen conserve l’état logique de l’interface.

Les identifiants, mots de passe, cookies et tokens ne doivent jamais être ajoutés au dépôt Git.

## Persistance locale

Le fichier `dashboard_session.json` contient notamment :

- les URL actives par tuile ;
- le zoom par tuile ;
- la page active ;
- la dernière tuile sélectionnée ;
- le focus ;
- l’état Split visible ;
- le plein écran ;
- la taille de fenêtre.

Depuis le correctif d’autosauvegarde, cet état est écrit **pendant l’exécution** avec un délai de debounce, au lieu de dépendre uniquement de `closeEvent()`.

## Mode Château Astra / VPS

NinoScreen peut fonctionner comme cockpit distant sur un VPS sans installation graphique système globale.

L’instance Château Astra validée utilise une pile user-space :

```text
NinoScreen / Qt WebEngine
        ↓
TigerVNC local
        ↓
noVNC + websockify authentifié
        ↓
porte HTTPS / réseau privé
        ↓
Vitrine Château Astra
```

Principes de sécurité retenus :

- VNC lié à localhost ;
- corpus Château hors du webroot public ;
- authentification séparée du cockpit ;
- aucun secret dans la vitrine ;
- profil navigateur persistant stocké hors du dépôt ;
- Chromium/QtWebEngine garde son sandbox quand le runtime le permet.

La vitrine publique et le cockpit privé restent deux couches différentes : **la vitrine montre, le cockpit agit**.

## Popups / nouvelles fenêtres

Les demandes de nouvelle fenêtre web sont redirigées dans la logique contrôlée par NinoScreen plutôt que de laisser proliférer des fenêtres natives indépendantes.

## Plein écran

Le plein écran global de NinoScreen est distinct du plein écran demandé par un site web afin d’éviter les conflits avec le mode focus et le mode Split.

## Structure principale

```text
ninoscreens/
├── main.py
├── requirements.txt
├── README.md
├── app/
│   ├── config.py
│   ├── session_store.py
│   ├── state.py
│   ├── web_profile.py
│   ├── focus_split_runtime.py
│   ├── widgets/
│   └── windows/
│       └── main_window.py
└── tests/
    ├── test_split_toggle.py
    └── test_session_autosave.py
```

## Tests ciblés actuels

- régression du bouton Split ON/OFF ;
- nettoyage des associations Split fantômes ;
- câblage de l’autosauvegarde débouncée ;
- compilation Python de l’application.

## Scénarios manuels recommandés

1. Lancer NinoScreen avec une session vide.
2. Charger plusieurs sites sur différentes pages.
3. Vérifier navigation et zoom indépendants.
4. Passer d’une page à l’autre.
5. Entrer en focus sur une tuile.
6. Activer puis désactiver Split.
7. Changer la tuile secondaire du Split.
8. Vérifier qu’aucune association Split fantôme ne subsiste.
9. Redimensionner la fenêtre.
10. Activer/désactiver le plein écran.
11. Vérifier que `dashboard_session.json` est créé **sans fermer l’application**.
12. Relancer NinoScreen et confirmer la restauration de la session.
13. Sur VPS, vérifier que VNC n’est pas exposé directement à Internet.
14. Vérifier l’accès au cockpit via la porte privée/authentifiée.
