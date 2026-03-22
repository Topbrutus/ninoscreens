# Multi-Site Dashboard

Application desktop locale Python / PySide6 / Qt Widgets / Qt WebEngine pour afficher et piloter 9 pages web indépendantes dans une grille 3x3.

## Fonctionnalités principales

- 9 carreaux indépendants, tous vides au démarrage la première fois
- Chargement d'URL par carreau avec normalisation robuste
- Navigation indépendante : retour, avancer, recharger
- Zoom indépendant par carreau
- **Mémoire persistante automatique** des pages ouvertes, par carreau
- **Restauration au démarrage** des URLs et du zoom de chaque carreau
- **Restauration du mode focus** si l'application a été fermée en focus
- **Barre mémoire 1 à 9** dans l'en-tête pour accéder rapidement aux carreaux
- **Bouton `🔄 Tout`** pour recharger tous les carreaux chargés
- Rail latéral de miniatures en mode focus
- Voyants d'état sur les miniatures
- Fermeture d'un carreau et retour à l'état vide
- Plein écran global de l'application
- Architecture modulaire, maintenable et extensible

## Dépendances

- Python 3.11+ recommandé
- PySide6 avec Qt WebEngine

## Installation

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

## Notes de conception

### Sessions web

La V1 utilise **un profil WebEngine partagé** entre les 9 carreaux.  
Cela permet un comportement cohérent pour les cookies, le cache et les sessions, tout en gardant une architecture prête à évoluer vers des profils séparés par carreau.

### Persistance locale

L'application enregistre localement un fichier de session avec :

- les URLs actives par carreau,
- le zoom par carreau,
- le carreau affiché en focus,
- la taille de la fenêtre.

Au prochain démarrage, la disposition logique est restaurée.

### Popups / nouvelles fenêtres

Les demandes `window.open()` et ouvertures de nouvelle fenêtre sont **redirigées dans le carreau courant** au lieu d'ouvrir une nouvelle fenêtre native non contrôlée.  
Cela garde la maîtrise de l'interface.

### Plein écran demandé par les sites

Le plein écran déclenché par une page web est **refusé** en V1 pour éviter les conflits avec :

- le mode focus de l'application,
- le plein écran global de l'application.

### Miniatures

Les miniatures sont des **captures pragmatiques du widget visible**.  
Quand un carreau n'est plus visible (par exemple si un autre carreau est affiché en mode focus), sa miniature conserve la dernière capture connue jusqu'à la prochaine mise à jour visible.  
C'est un compromis volontaire entre coût CPU/GPU, stabilité et utilité.

## Structure

```text
multisite_dashboard/
  main.py
  requirements.txt
  README.md
  app/
    __init__.py
    config.py
    session_store.py
    styles.py
    state.py
    url_utils.py
    web_profile.py
    widgets/
      __init__.py
      dashboard_grid.py
      focus_view.py
      thumbnail_rail.py
      web_tile.py
    windows/
      __init__.py
      main_window.py
```

## Scénarios manuels recommandés

1. Lancer l'application sans charger de site
2. Charger une seule URL
3. Charger 9 URLs
4. Vérifier que la barre mémoire 1-9 reflète les carreaux chargés
5. Utiliser les boutons 1-9 pour basculer rapidement en focus
6. Tester le bouton `💾` dans un carreau pour forcer une sauvegarde immédiate
7. Tester `🔄 Tout`
8. Fermer l'application avec plusieurs pages ouvertes
9. Relancer et vérifier la restauration
10. Tester une URL invalide
11. Utiliser retour / avancer / recharger
12. Tester le zoom
13. Fermer un carreau
14. Revenir à la grille
15. Redimensionner la fenêtre
16. Passer en plein écran global puis revenir
