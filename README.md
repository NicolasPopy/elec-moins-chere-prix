# Prix de l'électricité — base ElecMoinsChere

Base ouverte des prix de l'électricité pour les particuliers en France métropolitaine : tarif réglementé EDF (Tarif Bleu, Tempo) et offres de marché des principaux fournisseurs. Abonnement et prix du kWh **TTC pour chaque puissance de 3 à 36 kVA**, options (Base, heures creuses, Tempo, saisons, week-end…), promotions en cours, avantages, sources et niveau de fiabilité.

Mise à jour **chaque jour** automatiquement. Chaque mise à jour est un commit : l'historique Git est l'historique des prix.

## Consulter

- **Page lisible** : `index.html` (GitHub Pages) — choisir sa puissance, filtrer, trier par coût annuel.
- **Ce qui a changé** : [`CHANGELOG.md`](CHANGELOG.md).

## Réutiliser les données

| Fichier | Contenu | Pour qui |
|---|---|---|
| `data/offres.json` | Base complète (source de vérité) | site web, prompt, scripts |
| `data/offres.csv` | Une ligne par offre × puissance × poste horaire (séparateur `;`) | Excel, SQL, Google Sheets |
| `data/resume.json` | Classements par puissance et consommation (Base et HP/HC) | affichage rapide |
| `data/historique/AAAA-MM-JJ.json` | Copie de la base chaque jour | suivi des évolutions |

URL directe (lisible depuis n'importe quel site, CORS ouvert) :

```
https://raw.githubusercontent.com/NicolasPopy/elec-moins-chere-prix/main/data/offres.json
```

Exemple JavaScript :

```js
const d = await (await fetch("https://raw.githubusercontent.com/NicolasPopy/elec-moins-chere-prix/main/data/offres.json")).json();
const offre = d.offres.find(o => o.id === "edf-tempo");
const ligne = offre.grille.find(g => g.kva === 9);   // { kva, abonnement_mois, prix_kwh: { bleu_hp, ... } }
```

## Structure de `offres.json`

```jsonc
{
  "meta": { "mis_a_jour_le": "2026-10-30", "puissances_kva": [3,6,9,...], "postes": {...}, "options": {...} },
  "fournisseurs": [ { "id": "edf", "nom": "EDF", "site": "...", "type": "historique" } ],
  "offres": [ {
    "id": "edf-zen-online-hphc",            // identifiant stable
    "fournisseur": "edf",
    "offre": "Zen Online",
    "option": "hphc",                       // base | hphc | tempo | saisons | saisons_rouge | week_end | flex
    "type_prix": "indexe_trv",              // reglemente | indexe_trv | fixe | variable
    "duree_prix_garanti_mois": null,
    "indexation": "Indexé sur le Tarif Bleu",
    "energie_verte": { "niveau": "standard", "detail": "Garanties d'origine" },
    "engagement": "sans engagement",
    "plages_horaires": "…",                 // texte : quand s'appliquent les prix
    "grille": [ { "kva": 6, "abonnement_mois": 15.86, "prix_kwh": { "hp": 0.2059, "hc": 0.1531 } } ],
    "promotions": [ { "description": "…", "valeur_an1_eur": 100, "nouveaux_clients": true, "date_fin": "2026-11-30", "conditions": "…", "source": "…" } ],
    "avantages": [ "…" ],
    "verification": "confirme",             // confirme | source_unique | conflit
    "sources": [ { "url": "…", "type": "officiel", "consulte_le": "2026-10-30" } ],
    "notes": [ "…" ],
    "derniere_verif": "2026-10-30"
  } ]
}
```

Les postes horaires (`base`, `hp`, `hc`, `bleu_hp`, `ete_hsc`, `week_end`…) sont décrits en clair dans `meta.postes`. Une ligne de grille avec `"ouvert_nouveaux_clients": false` n'est plus proposée à la souscription (ex. Tarif Bleu Base au-delà de 6 kVA).

## Fiabilité

- **Confirmée** : deux sources concordent, ou grille officielle du fournisseur.
- **1 source** : une seule source trouvée.
- **À vérifier** : les sources divergent ; la valeur retenue est la plus fiable, l'autre figure dans `notes`.

Vérifiez toujours sur le site du fournisseur avant de souscrire.

## Mettre à jour

La mise à jour quotidienne suit [`MISE-A-JOUR.md`](MISE-A-JOUR.md) : modifier `data/offres.json`, puis

```
python3 scripts/build.py --check   # valide
python3 scripts/build.py           # régénère CSV, résumé, historique, CHANGELOG et index.html
```

La validation refuse un prix hors bornes, un poste manquant, une source absente ; elle signale les promotions expirées et les offres non revérifiées depuis plus de 14 jours.
