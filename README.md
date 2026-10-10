# Recap Montres Hebdo

Bot Telegram qui envoie chaque semaine un récap des nouveautés horlogères,
automatiquement, gratuitement, via GitHub Actions.

## 1. Tester en local

```bash
pip install -r requirements.txt

# Sur Mac/Linux :
export TELEGRAM_TOKEN="ton_token"
export TELEGRAM_CHAT_ID="@tonchannel"

# Sur Windows (PowerShell) :
$env:TELEGRAM_TOKEN="ton_token"
$env:TELEGRAM_CHAT_ID="@tonchannel"

python recap_montres.py
```

Si tout va bien, tu dois voir le message s'afficher dans le terminal
ET apparaître dans ton canal Telegram.

## 2. Mettre en ligne sur GitHub

1. Crée un repo (privé si tu veux) et pousse tout ce dossier dedans.
2. Va dans **Settings → Secrets and variables → Actions → New repository secret**.
3. Ajoute deux secrets :
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Va dans l'onglet **Actions** du repo, sélectionne le workflow
   "Recap Montres Hebdo", clique sur **Run workflow** pour tester
   manuellement une première fois.

## 3. Ajuster les sources

La liste des flux RSS est dans `recap_montres.py`, variable `RSS_FEEDS`
en haut du fichier. Ajoute ou retire des tuples `(nom, url_du_flux)`.

Pour trouver le flux RSS d'un site qui n'est pas listé, cherche
généralement `site.com/feed` ou `site.com/rss`.

## 4. Changer la fréquence

Le planning est dans `.github/workflows/weekly.yml`, ligne `cron`.
Format : `minute heure jour mois jour-semaine` (en UTC).
Exemple actuel : `0 8 * * 1` = tous les lundis à 8h UTC (9h Paris en hiver).

## Prochaines améliorations possibles (une à la fois !)

- Filtrer par marque précise
- Détecter et afficher les prix quand ils sont mentionnés
- Ajouter une image à chaque article (nécessite l'API Telegram `sendPhoto`)
- Déduppliquer si un même modèle est couvert par plusieurs sources
