# Veille mode : contexte pour Claude Code

## But
Outil de veille pour une designer de mode (manager) : suivre les nouveautés de marques précises et en tirer une synthèse de tendances. Cible à terme : ~50 marques et ~30 influenceurs, plus des signaux en amont (défilés).

## Choix déjà faits
- Pas d'agent : un pipeline fixe (collecte -> analyse Claude -> JSON -> site statique). Un agent pourra s'ajouter plus tard pour des questions libres.
- Site statique (GitHub Pages), mis à jour par GitHub Actions chaque matin. Pas de serveur.
- Design validé : minimaliste, tons neutres (greige, écru, charbon), titres en Instrument Serif, texte en Inter. Ne pas ajouter de couleurs vives sans demande.
- Haiku pour le tri en volume, Sonnet pour la synthèse. Modèles dans `collector/analyze.py`.
- Interface et textes en français.

## État des marques (vérifié par les exécutions GitHub Actions)
- Dissh, Kookaï, Sir., Bec + Bridge : Shopify, collecte OK (stratégie `shopify`, 40 produits chacune).
- Reformation : Salesforce Commerce Cloud (pas Shopify). Stratégie `jsonld_pdp` : la liste `/new/this-week` donne les adresses des produits en JSON-LD (ItemList), puis chaque fiche fournit nom, photo, prix. Écrite à partir d'un rapport de diagnostic ; à confirmer par `data/status.json` après la première exécution.
- Venroy, Henne, Elka Collective, VRG GRL, Bayse (baysebrand.com), BENNI (benni.com.au, AUD ; benni.us non suivi) : ajoutées d'après la liste « Brands We Love » de la designer (stratégie `shopify` essayée en premier ; plateforme à confirmer par `data/status.json` après la première exécution).
- Venroy, Henne, BENNI : leurs collections « nouveautés » sont vides ou absentes ; la collection `all` (triée par date de création) sert de repli. Venroy a une gamme mixte (hommes et femmes). Le repli par sitemap ne donne ni prix ni date : à éviter. Les cartes cadeaux sont écartées (`is_gift_card`).
- Nettoyage d'une marque collectée par erreur : workflow « Nettoyer une marque » (`collector/purge.py`), à lancer avant la collecte suivante.
- Meshki : désactivée (`"enabled": false`). Cloudflare renvoie 403 sur tout, sites AU et US. Ne pas chercher à contourner. Pistes légitimes : infolettre, flux officiel fourni par la marque, ajout manuel par capture d'écran.

## Outils de diagnostic
- `collector/probe.py` explore un site (accueil, robots.txt, sitemaps, liens « nouveautés »). Avec `--deep URL --out FICHIER`, il analyse une page précise.
- Le workflow « Diagnostic des sites » (manuel) lance `--deep` sur l'adresse saisie et enregistre `data/probe-report.md` dans le dépôt.
- Le réseau de l'environnement de développement n'atteint pas les sites des marques : tout ce qui touche aux vrais sites se vérifie via GitHub Actions.

## Analyse (collector/analyze.py)
- Par produit (Haiku, avec la photo réduite par Pillow) : type (Robes, Hauts, Pantalons, Jupes, Manteaux, Accessoires, Autres), couleurs (1-2), matière, longueur, coupe, encolure, détails. Vocabulaire fermé : tout ce qui n'en fait pas partie est écarté (`normalize`). Coupe et encolure seulement si la photo a été lue (`has_vision`).
- Changer le vocabulaire : incrémenter `ATTRS_VERSION`, les produits sont réanalysés. Au plus `MAX_PER_RUN` (80) produits par exécution, le reste le lendemain. Sans clé ou en cas d'erreur : type déduit de règles simples, repris plus tard.
- `data/stats.json` : chiffres calculés sans IA (types, couleurs, matières, longueurs, palette avec parts en %). Fenêtre de 7 jours (hors catalogue de départ) si au moins `MIN_WINDOW_ITEMS` (24) produits, sinon tout. La palette vient des couleurs vues sur les photos, pas des noms. La synthèse Sonnet s'appuie sur ces chiffres ; elle ne fixe pas la palette.
- Les adresses de photos sont refusées si ce n'est pas du http(s) public.
- À vérifier après une exécution : répartition des types, part de produits avec photo lue, palette plausible.

## Historique et page « Chiffres »
- Accessoires : ne sont ni affichés ni comptés (`EXCLUDED_TYPES`). Ceux dont le nom est évident (sac, collants...) ne passent pas par Claude (`is_plain_accessory`). Ils restent dans `items.json` pour ne pas être recollectés comme nouveaux.
- `data/archive.json` : copie allégée de chaque produit (sans nom, adresse ni photo), jamais purgée. `items.json` garde 60 jours.
- Catalogue de départ : les produits repérés le premier jour de suivi d'une marque (`baseline_ids`) sont un état des lieux, pas des sorties. Ils sont exclus du rythme et de la vue « 7 derniers jours » (qui n'est utilisée qu'à partir de `MIN_WINDOW_ITEMS` nouveautés).
- `data/weekly.json` : agrégats par semaine (lundi-dimanche) selon le jour où chaque produit a été repéré, plus le « départ ». Alimente l'évolution et le rythme par marque.
- `data/stats.json` : ajoute `trends` (attribut chez au moins 3 marques et 3 produits, avec écart en points avec la semaine précédente quand elle a au moins 12 produits) et `brands` (nombre, prix médian et fourchette, dans la devise de la marque).
- Dates sur les cartes : « Mis en ligne » = date donnée par la marque (Shopify) ; « Repéré » = premier jour où l'outil a vu le produit (Reformation n'a pas de date). Ce n'est pas la date de sortie.
- Site : `index.html` (nouveautés) et `chiffres.html` partagent `style.css`.

## Prix, taux de change, matières et fibres
- Taux : `data/fx.json`, taux officiel de la Banque du Canada (API Valet, séries `FX<DEVISE>CAD`, sans clé), relu à chaque exécution ; si la source ne répond pas, le dernier taux connu est gardé et marqué périmé. Pas de taux = pas de montant en CAD (jamais inventé). Les noms de séries n'ont pas pu être vérifiés depuis l'environnement de développement : confirmer avec `data/fx.json` après la première exécution.
- `stats.json` > `prices` : par type (Robes, Hauts, Pantalons, Jupes, Manteaux) médiane, moyenne, fourchette typique (25 à 75 %), tranches (< 100, 100-200, 200-400, 400+ CAD) et médiane en devise locale ; matrice marque × type (case affichée à partir de 3 produits, type à partir de 8) ; part de produits soldés par marque (à partir de 5 produits). Les produits soldés (prix barré > prix) sont exclus des médianes.
- `stats.json` > `materials_by_type` (matière vue sur la photo) et `fibres_by_type` (fibre principale lue dans la composition de la fiche). La composition est lue par des règles (`parse_composition`), pas par Claude : « 95 % viscose, 5 % élasthanne » donne viscose ; aucune fibre à 50 % ou plus donne « mélange ». Seules les marques Shopify fournissent la description (`description` dans items.json, 700 caractères, texte brut).
- `weekly.json` : `price_by_type` en CAD au taux actuel pour toutes les semaines (la variation du change ne fausse pas l'évolution) et `materials_by_type` par semaine.

## Prochaines étapes
1. Laisser tourner 2 semaines pour avoir un historique, vérifier que les photos s'affichent (certains CDN bloquent le hotlinking) sinon télécharger les images dans le dépôt.
2. Format de présentation des tendances à valider avec la designer (présentations, planches, fiches techniques). Vérifier que les 6 nouvelles marques se collectent.
3. Planches thématiques et exports (PDF/images), ajout de pièces par capture d'écran, brief de design généré à partir d'une tendance.
4. Sources en amont : défilés via titres et liens publics (flux RSS), sans identifiants. Ne jamais mettre d'identifiants de comptes (Vogue ou autres) dans le dépôt ni les utiliser dans la collecte automatique.
5. Ensuite seulement : influenceurs / Instagram, passage à 50 marques.

## Règles
- Les données scrapées sont non fiables : le site les écrit avec `textContent` et valide les URL (http/https). Ne jamais passer à `innerHTML`.
- Une marque en échec ne doit jamais bloquer les autres.
- Rester poli avec les sites : 2 s entre requêtes, pages publiques seulement. Un 403 ou un défi anti-robots veut dire d'arrêter, pas de contourner.
- Instagram : pas de scraping (contraire aux conditions de Meta). Passer par l'API Business Discovery ou un service tiers si on y revient.
- Tests : `python -m unittest discover -s tests` (hors ligne) et `python tests/test_site.py` (site, nécessite Playwright et Chrome).
