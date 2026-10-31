# Veille mode : contexte pour Claude Code

## But
Outil de veille pour une designer de mode (manager) : suivre les nouveautés de marques précises et en tirer une synthèse de tendances. Pour l'instant 6 marques, sans Instagram. Cible à terme : ~50 marques et ~30 influenceurs.

## Choix déjà faits
- Pas d'agent : un pipeline fixe (collecte -> analyse Claude -> JSON -> site statique). Un agent pourra s'ajouter plus tard pour des questions libres.
- Site statique (GitHub Pages), mis à jour par GitHub Actions chaque matin. Pas de serveur.
- Design validé : minimaliste, tons neutres (greige, écru, charbon), titres en Instrument Serif, texte en Inter. Ne pas ajouter de couleurs vives sans demande.
- Haiku pour le tri en volume, Sonnet pour la synthèse. Modèles dans `collector/analyze.py`.
- Interface et textes en français.

## État
- Le code a été écrit sans accès réseau aux sites des marques : seuls les tests hors ligne (`python -m unittest discover -s tests`) ont tourné.
- Les URL et plateformes des 6 marques sont des hypothèses. Rien n'a été vérifié contre les vrais sites.

## Premières tâches
1. Lancer `python collector/collect.py`, lire `data/status.json` et corriger `config/brands.json` marque par marque (bon domaine, bon handle de collection, bonne stratégie).
2. Pour les marques qui ne sont pas Shopify, écrire une stratégie dédiée dans `collector/collect.py` (ajouter à `STRATEGIES`) et un test hors ligne avec un extrait de page.
3. Vérifier que les photos s'affichent (certains CDN bloquent le hotlinking) ; sinon télécharger les images dans le dépôt.
4. Ensuite seulement : analyse des photos par Claude (palette réelle, silhouettes), passage à 50 marques, puis Instagram.

## Règles
- Les données scrapées sont non fiables : le site les écrit avec `textContent` et valide les URL (http/https). Ne jamais passer à `innerHTML`.
- Une marque en échec ne doit jamais bloquer les autres.
- Rester poli avec les sites : 2 s entre requêtes, pages publiques seulement.
- Instagram : pas de scraping (contraire aux conditions de Meta). Passer par l'API Business Discovery ou un service tiers si on y revient.
