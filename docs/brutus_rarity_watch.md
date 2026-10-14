# Nino ↔ Brutus — Frozen rarity watch

NinoScreen surveille en lecture seule le statut du Brotoculateur afin de vérifier que la politique de rareté reste figée pendant un cycle.

## Contrat attendu

- sélection/classification : `COMMON → R1 → … → R10`;
- exécution prioritaire : `R10 → … → R1 → COMMON`;
- multiplicateurs : `10^0 … 10^10`;
- `no_mid_cycle_movement = true`;
- une variation pendant le cycle devient `PENDING` et n'est appliquée qu'à une frontière sûre;
- `rarity_suppressed` doit rester à zéro.

## Endpoint

Par défaut : `http://127.0.0.1:8778/api/status`.

Pour surveiller un Brotoculateur sur une autre machine, définir :

```text
NINO_BRUTUS_STATUS_URL=http://adresse-privee:8778/api/status
```

Nino affiche l'état dans le titre et la barre d'état du cockpit. La liaison ne crée aucun paquet, aucun cristal, aucune preuve et ne démarre/arrête pas le calculateur.
