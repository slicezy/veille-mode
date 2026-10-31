# Veille mode

Un petit site qui suit les nouveautés de 6 marques (Reformation, Dissh, Kookaï, Sir., Bec + Bridge, Meshki), les classe avec Claude et affiche un moodboard mis à jour chaque matin.

```
config/brands.json     les marques suivies
collector/collect.py   collecte (Shopify, JSON-LD, sitemap) -> data/items.json + data/status.json
collector/analyze.py   Claude : catégories, couleurs, synthèse -> data/digest.json
site/index.html        le site statique (lit data/*.json)
.github/workflows/     exécution quotidienne + publication
tests/                 tests hors ligne
```

## Mise en route

1. Créer un dépôt GitHub et y pousser ce dossier.
2. Dépôt > Settings > Secrets and variables > Actions > New repository secret : `ANTHROPIC_API_KEY`.
3. Dépôt > Settings > Pages > Source : **GitHub Actions**.
4. Onglet Actions > « Veille quotidienne » > **Run workflow**. Le site est en ligne quelques minutes après.

Le site publié est accessible à toute personne qui a le lien (même si le dépôt est privé). Il ne contient que des nouveautés publiques de marques. Pour le protéger, Cloudflare Pages avec Cloudflare Access est l'alternative.

## Premier lancement : lire `data/status.json`

Les URL des marques dans `config/brands.json` sont des hypothèses, et la plateforme de chaque site n'a pas été vérifiée. Après la première exécution, `data/status.json` indique pour chaque marque quelle méthode a fonctionné, combien de produits ont été trouvés, et les erreurs éventuelles. Une marque sans produit n'empêche pas les autres de s'afficher.

## En local

```bash
pip install -r requirements.txt
python collector/collect.py                 # ou --only meshki
ANTHROPIC_API_KEY=... python collector/analyze.py
mkdir -p _site && cp -r site/* _site/ && cp -r data _site/data
python -m http.server -d _site 8000         # puis ouvrir http://localhost:8000
python -m unittest discover -s tests
```

## Coûts et limites

- Coût API : quelques dollars par mois (Haiku pour le tri, un seul appel Sonnet par jour pour la synthèse).
- Le collecteur attend 2 s entre deux requêtes et ne lit que des pages publiques. Vérifier les conditions d'utilisation et le `robots.txt` de chaque marque avant d'étendre.
- La palette est déduite des noms de produits. Une version plus fidèle analyserait les photos.
