# 🧠 Votre Mémo — depaneurIA

## Les 5 commandes que vous utiliserez tout le temps

```bash
cd ~/depaneurIA          # Aller dans votre projet
pnpm install             # Installer les dépendances (après un git pull)
pnpm dev                 # Lancer le site en local (pour tester)
git add . && git commit -m "mon message" && git push   # Sauvegarder sur GitHub
```

## Vocabulaire rapide

| Mot              | Ce que ça veut dire pour vous                        |
|------------------|------------------------------------------------------|
| **Terminal**     | La fenêtre noire où on tape des commandes            |
| **Repo / dépôt** | Votre projet sur GitHub                              |
| **Commit**       | Une sauvegarde de vos changements                    |
| **Push**         | Envoyer vos sauvegardes sur GitHub                   |
| **pnpm install** | Télécharger les "pièces" dont le projet a besoin     |
| **pnpm dev**     | Lancer le site sur votre ordi (localhost:3000)       |
| **build**        | Préparer le site pour le mettre en ligne             |
| **monorepo**     | Un seul projet qui contient plusieurs apps           |
| **package.json** | La "liste d'épicerie" des dépendances du projet      |

## Structure de votre projet

```
depaneurIA/
├── apps/
│   ├── web-store/     ← L'interface du dépanneur (ce qu'on construit)
│   ├── web-client/    ← Interface client (plus tard)
│   └── api/           ← Backend (plus tard)
├── packages/          ← Code partagé entre les apps
└── docs/              ← Documentation
```

## Votre site en local

Une fois lancé avec `pnpm dev` :
- Interface dépanneur → http://localhost:5173
- API backend → http://localhost:3000

## En cas de problème

```bash
# Le site ne démarre pas ?
pnpm install        # Réinstaller les dépendances

# Erreur bizarre ?
git status          # Voir ce qui a changé

# Tout est cassé ?
git stash           # Annuler vos derniers changements non sauvegardés
```
