# E0 — État de l'art

> Veille réalisée le 2026-09-20. Critère de passage E0 : « rien d'équivalent en continu, ou pivot décidé ».
> **Verdict : critère tenu. Aucun observatoire continu équivalent n'existe. On passe à E1.**
> Toute affirmation ci-dessous est sourcée. Les chiffres cités sont ceux des auteurs, non recalculés par nous.

---

## 1. Verdict en une phrase

La littérature sur le *link rot* des artefacts de recherche est faite d'**instantanés rétrospectifs, mono-discipline ou mono-institution, jamais rejoués** ; les outils existants (`metacheck`) sont des **briques de vérification**, pas des mesures publiées à l'échelle ; les tableaux de bord existants mesurent le **statut d'accès de l'article**, pas la survie de ses artefacts. La **courbe de survie publique, multi-disciplines, multi-éditeurs et rejouable** que vise `artifact-rot` n'existe pas.

## 2. Ce qui existe

### 2.1 Études ponctuelles — les points de comparaison du rapport E6

| Étude | Périmètre | Chiffre principal | Pourquoi ce n'est pas notre mesure |
|---|---|---|---|
| **Caltech « Measuring data rot »** (PLOS ONE, 2024) — 2 166 liens supplémentaires, 1 419 notices, publications 2014–2022 (80,7 % de 2020–2022) | Une université | **5,4 %** des liens indisponibles ; **1,7 %** pour les DOI contre **5,9 %** pour les URL | Une institution, corpus très récent (donc biais de survie massif), sondage unique en mai 2023, complété **manuellement** au navigateur. Les auteurs reconnaissent qu'il manque ~la moitié des liens réels par erreur de curation. |
| **PLOS ONE long terme** (2022) — ~50 000 *Data Availability Statements*, 8 503 URL et DOI | Une revue | **80 %** des ressources récupérables automatiquement ; **78 %** des URL, **98 %** des DOI | Une revue, un instantané. Confirme l'écart URL/DOI. |
| **American Astronomical Society** | Une discipline | **44 %** des liens de 10 ans ne résolvent pas | L'ordre de grandeur qui rend H1 plausible sur la strate ancienne. |
| **Artefacts en génie logiciel** (arXiv 2404.06852) | Une discipline | **9,4 %** de rot moyen ; **32,6 %** sur Dropbox/Google Drive, **11,8 %** sur pages perso, **6,4 %** GitHub, **7,1 %** Zenodo | Le gradient par type d'hébergeur — exactement la déclinaison prévue au §6 du plan, mais sur une seule discipline. |
| **« Knock knock! Who's there? »** (arXiv 2207.12879) | 13 000+ URL de *dépôts* issues de FAIRsharing, re3data, OpenDOAR, ROAR | Disponibilité « loin d'être acquise » | Mesure la page d'accueil **du dépôt**, pas le lien vers l'artefact d'un article. Instantané unique de juillet 2022. |
| **Décroissance d'URL dans MEDLINE**, **link rot en LIS sur 20 ans** | Références bibliographiques | Demi-vie estimée entre **4 et 14 ans** selon les corpus | Portent sur les **citations web**, pas sur les artefacts annoncés comme disponibles. Fixent néanmoins l'ordre de grandeur attendu de notre demi-vie. |

**Conséquence pour le §2 du plan.** Le seuil H1 de `20 %` sur la strate 2018 est cohérent avec cette littérature sans être garanti : Caltech mesure 5,4 % sur un corpus quasi contemporain, l'AAS mesure 44 % à 10 ans. Une strate 2018 (8 ans d'âge) se situe entre les deux. Le seuil n'est pas renégocié — il est simplement constaté comme non trivialement atteint, ce qui est la condition pour qu'il soit un test.

### 2.2 `scienceverse/metacheck` — la brique à ne pas réimplémenter

- **Nature** : paquet **R**, licence **AGPL-3.0**, cycle de vie déclaré « expérimental ». But affiché : vérifier automatiquement les productions de recherche face aux bonnes pratiques. Successeur de `scienceverse/papercheck`.
- **Écosystème** : `scienceverse/bibr` est le pipeline d'extraction amont (PDF, DOCX, JATS XML, HTML, ePub → JSON versionné : métadonnées, références, texte intégral, tableaux, figures).
- **Ce qui est réutilisable ici** : l'outil est en R et sous AGPL-3.0, notre pile est Python. **Aucune reprise de code n'est possible sans contaminer la licence ni traduire.** Ce qui se reprend, et qui a plus de valeur que le code : ses **modes d'échec documentés**, listés ci-dessous. Ils sont le fruit d'un travail sur corpus réel que nous n'aurons pas à refaire.
- **Ce qui se contribue en retour** : nos sondes d'existence (§4 du plan) et notre jeu de contrôle E2 sont exactement ce dont `metacheck` manque publiquement. Contribution envisagée après E2, pas avant : on ne propose rien avant d'avoir un chiffre de fiabilité.

**Modes d'échec de l'extraction de liens, mesurés par `metacheck` sur le corpus de validation Cooper (1 861 articles)** — *issue #411*. À traiter comme spécification de tests pour E3, pas comme anecdote :

1. **Section « références » exclue par défaut.** Les 14 backends de recherche textuelle utilisent `include_refs = FALSE`. Un DOI de dépôt cité uniquement en bibliographie sous la forme `Data from: Auteur (Année). Titre [Dataset]. https://doi.org/…` devient invisible. **55 articles sur 1 861 (3 %)** concernés.
2. **Césure d'URL par GROBID.** L'extraction PDF→texte insère des espaces dans les URL : `https://doi. org/10.7939/DVN/QYMAYV`. Présent dans **1 582 articles sur 1 861 (85 %)**, le plus souvent sans conséquence, mais fatal quand un DOI de dépôt tombe sur une fin de ligne.
3. **Motif Figshare non couvert.** Les URL `/articles/<slug>/<id>`, sans segment de type de ressource, ne sont pas parsées et renvoient `NA` alors que le lien a bien été détecté.

→ **Décision d'ingénierie, prise ici** : `normalize.py` applique une normalisation d'espaces **avant** toute regex (piège 2) ; `links.py` traite la bibliographie comme une source à part, marquée, avec le risque de fausse attribution signalé dans le schéma plutôt qu'écarté en silence (piège 1) ; le motif Figshare `/articles/[^/]+/([0-9]+)` est couvert dès le départ (piège 3). Ces trois cas entrent dans `tests/` comme régressions nommées.

### 2.3 Matière première

`OpenAlex`, `Crossref`, `DataCite` : données ouvertes, API gratuites. Ce sont les entrées, pas des résultats. OpenAlex fournit l'échantillonnage stratifié (E1) et le statut d'accès ouvert ; DataCite et Crossref résolvent les DOI de jeux de données.

### 2.4 Tableaux de bord existants

Les tableaux de bord d'*open access* (HOAD et le paysage recensé dans *Scientific Data*, 2026) suivent le **statut OA de l'article**. Aucun ne suit la résolution des liens annoncés **dans** l'article. Recherche menée explicitement sur ce point : aucun service public, continu, de vérification de résolution des liens de *Data Availability Statements* n'a été trouvé.

## 3. Ce qui manque — l'apport propre, reformulé après veille

Trois choses qu'aucune des sources ci-dessus ne produit ensemble :

1. **La continuité.** Toutes les études sont des sondages uniques. Aucune n'est rejouable : la méthode est décrite, le code et l'échantillon rarement publiés, et personne ne recommence six mois plus tard.
2. **Le croisement âge × discipline × hébergeur × éditeur.** Chaque étude tient une seule de ces variables. L'effet d'âge de l'AAS et l'effet d'hébergeur du génie logiciel n'ont jamais été mesurés sur le même corpus.
3. **La demi-vie comme livrable.** Aucune des études ne publie de courbe de survie avec censure à droite. Les chiffres de 4 à 14 ans circulant dans la littérature portent sur des **citations web**, pas sur des artefacts de recherche, et sont des estimations dérivées de taux bruts.

## 4. Ce que la veille change au plan

Rien sur le périmètre (§3), rien sur les seuils (§2), rien sur la règle d'arrêt. Trois ajouts d'exécution :

- Les trois modes d'échec `metacheck` deviennent des tests de régression nommés en E3.
- Le rapport E6 comparera ses chiffres à Caltech (5,4 %), PLOS ONE (80 % récupérables), AAS (44 % à 10 ans) et génie logiciel (9,4 %), en signalant à chaque fois la différence de périmètre. Un chiffre isolé est contestable ; un chiffre situé dans une littérature l'est moins.
- La méthode de Caltech (vérification **manuelle** au navigateur des échecs) est ce que notre §4 interdit. C'est un argument de différenciation à écrire dans le rapport : notre classification est entièrement déterministe et donc rejouable, au prix d'une catégorie `unknown` assumée et reportée à part.

## 5. Sources

- [Measuring data rot: continued availability of shared data from a Single University — PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0304781)
- [Long-term availability of data associated with articles in PLOS ONE](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9401135/)
- [Inaccessible data sharing: Link rot in the Data Availability Statement](https://www.researchgate.net/publication/367547002_Inaccessible_data_sharing_Link_rot_in_the_Data_Availability_Statement)
- [Research Artifacts in Software Engineering Publications: Status and Trends — arXiv 2404.06852](https://arxiv.org/pdf/2404.06852)
- [« Knock knock! Who's there? » A study on scholarly repositories' availability — arXiv 2207.12879](https://arxiv.org/abs/2207.12879)
- [An update on URL decay in MEDLINE abstracts](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2435527/)
- [Link rot in LIS literature: a 20-year study](https://www.researchgate.net/publication/399761240_Link_rot_in_LIS_literature_a_20-year_study_of_web_citation_decay_recovery_and_preservation_challenges)
- [scienceverse/metacheck](https://github.com/scienceverse/metacheck) · [issue #411](https://github.com/scienceverse/metacheck/issues/411) · [scienceverse/bibr](https://github.com/scienceverse/bibr)
- [Mapping the Landscape of Open Access Dashboards — Scientific Data](https://www.nature.com/articles/s41597-026-07217-z)
- [OpenAlex](https://openalex.org/) · [documentation développeurs](https://developers.openalex.org)
