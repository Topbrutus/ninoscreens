# LinuxIA CLI dans NinoScreens

Ce dossier devient le point de regroupement de **LinuxIA CLI** et de **Antmux** dans le dépôt NinoScreens.

## Organisation

- `antmux/` : sous-module Git pointant vers la branche d’intégration sécurisée de `Topbrutus/Antmux`;
- le shell LinuxIA, ses tests et sa documentation sont consolidés sur cette branche avant fusion;
- aucun modèle Ollama, cache, journal local, secret ou sauvegarde machine n’est versionné.

## Branche de travail

La migration est préparée sur `linuxia-cli-antmux-integration`. `main` reste intact jusqu’à validation des tests et revue de la pull request.

## Défilement du terminal

Le travail en cours ajoute un historique en mémoire affiché au-dessus du titre LinuxIA, avec navigation `PgUp` / `PgDn` et commandes `/haut`, `/bas`, `/fin`. Aucun journal conversationnel persistant n’est créé automatiquement.
