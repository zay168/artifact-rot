# Plan d'implémentation — Observatoire de la survie des artefacts de recherche

> Fichier à déposer à la racine du repo. À lire intégralement par Claude Code avant la première ligne de code.
> Nom de code : `artifact-rot`. Le nom public se décide après le premier rapport.
> Ce plan remplace les deux précédents (`calibration-bench`, `provenance-watch`), abandonnés : coût d'annotation pour l'un, périmètre IA non voulu pour l'autre.

---

## 0. Cadre de travail (prime sur les habitudes par défaut de l'agent)

### Registre
- **Vers Zayd** (diagnostic, résultat, estimation) : strictement factuel. Aucun chiffre embelli, aucune félicitation de politesse.
- **Vers l'extérieur** (rapport, README, site) : cadrage et sélection assumés, faits intouchables. Le projet mesure la rigueur d'autrui — la moindre approximation est un boomerang.

### Calibrage épistémique
Ce projet mesure **des réponses HTTP et des résolutions d'identifiants**, pas de l'honnêteté scientifique. Distinction structurante, tenue dans chaque ligne de code comme de rapport :
- Mesuré : « au 20 septembre 2026, ce lien ne résout pas ».
- Non mesuré, jamais affirmé : « ces auteurs n'ont pas partagé leurs données ».
Un lien mort peut venir d'une migration d'université, d'un dépôt renommé, d'un serveur en panne ce jour-là. Le rapport le dit, et mesure quand même — parce que du point de vue du lecteur qui veut reproduire, le résultat est le même.

### Posture
- **Livrer fini.** Pas d'esquisse en attente de relance. Le cas limite se traite avant qu'il se présente.
- **Autonomie.** Trancher les détails d'exécution seul. Une seule question, et seulement si l'ambiguïté change le résultat ; sinon choisir l'option la plus défendable et signaler l'hypothèse en une ligne.
- **Franchise.** Dire quand un chemin est mauvais, un chiffre faux, une hypothèse morte. La critique porte sur le chemin, jamais sur la hauteur de la cible.
- **Zéro complaisance.**

### Toujours à jour
`scienceverse/metacheck` existe et fait déjà de l'extraction et de la résolution de liens de dépôts depuis des papers — **le lire, l'évaluer, le réutiliser ou contribuer plutôt que réimplémenter**. Idem pour les clients OpenAlex et Crossref. Réimplémenter une brique existante est une faute de méthode au même titre que partir de zéro sans regarder. Le code dit en commentaire : ce qui est repris, d'où, et où est l'apport propre.

### Conduite
- **Descartes** : décomposer, ordonner du simple au composé, dénombrement exhaustif des états possibles d'un lien.
- **Bacon** : tester en premier l'hypothèse la plus fragile, avec la plus petite expérience qui la casse (§2).
- **Clausewitz** : centre de gravité = **la fiabilité de la classification d'un lien mort**. Tout le reste en découle. Friction attendue : les faux positifs de crawl.
- **Sun Tzu** : ne livrer que les batailles gagnées sur le papier. Aucun front supplémentaire avant le verdict de S1.
- **Franklin** : métrique écrite, mesurée avant d'être optimisée.

### Règle d'arrêt
Si H1 (§2) est réfutée — les liens survivent bien — on publie le résultat positif, qui est une information publiable en soi, et on s'arrête. Pas d'entretien par inertie.

---

## 1. Objet

Mesurer, à grande échelle et en continu, **si les liens vers le code et les données annoncés dans les articles scientifiques résolvent réellement**, et à quelle vitesse ils meurent.

### L'astuce structurelle : coût d'annotation nul
La vérité terrain est un **code de réponse HTTP** et une **résolution d'identifiant**. Aucun humain n'a jamais à juger quoi que ce soit. Le label est produit par la machine, gratuitement, sur des millions de cas.

C'est le principe général, réutilisable bien au-delà de ce projet : quand la vérité terrain coûte cher, on déplace l'expérience vers un terrain où elle se fabrique toute seule. Ici, le monde répond lui-même.

### Le second atout : l'âge fabrique la série temporelle
Contrairement à un observatoire classique qui doit attendre des mois avant d'avoir une courbe, celui-ci en produit une **dès le premier run** : on échantillonne des articles de 2010, 2014, 2018, 2022, 2025, on teste tout aujourd'hui, et la courbe de survie en fonction de l'âge sort immédiatement. Le suivi continu ajoute ensuite la dimension prospective.

Conséquence : un chiffre publiable existe après quelques semaines, pas après un an. C'est ce qui rend le projet tenable pour une personne seule.

### Ce qui existe, ce qui manque
| Existe | Nature | Pourquoi ça ne couvre pas |
|---|---|---|
| Études de « data rot » (PLOS One, une université ; PLOS ONE long terme) | Ponctuel, rétrospectif, périmètre étroit | Un instantané, une discipline, jamais rejoué |
| `scienceverse/metacheck` | Outil d'extraction et de vérification | Brique, pas mesure publiée à l'échelle |
| Tableaux de bord Open Access (HOAD, etc.) | Suivent le statut OA | Mesurent l'accès à l'article, pas la survie de ses artefacts |
| OpenAlex, Crossref, DataCite | Données ouvertes, API gratuites | Matière première, pas résultat |

**Apport propre** : l'échelle (multi-éditeurs, multi-disciplines), la continuité, et la **courbe de survie** — la demi-vie d'un lien de données, chiffre qui n'existe nulle part sous forme publique et rejouable.

---

## 2. Hypothèse à casser en premier (jalon S1)

**H1 — Une part substantielle des liens de code et de données annoncés dans les articles ne résout plus, et le taux de mort croît nettement avec l'âge de l'article.**

Critère de décision, écrit **avant** le premier run, non renégociable après avoir vu les résultats :
- **H1 tenue** si le taux de liens non résolus dépasse `20 %` sur la strate 2018, **et** si l'écart entre la strate la plus ancienne et la plus récente dépasse `15 points`, IC 95 % (Wilson) excluant 0 sur les deux.
- **H1 réfutée** si le taux reste sous 20 % partout ou si l'effet d'âge est nul.
- Zone grise : élargir l'échantillon **une seule fois**, à un facteur 3. Pas de deuxième extension.

Hypothèse la plus fragile, à tester avant tout (Bacon) : **la classification d'un lien mort est-elle fiable ?** Si le crawler produit 30 % de faux positifs, le chiffre principal est du bruit et le projet est mort. C'est E2 (§7), et c'est le premier code à écrire.

---

## 3. Périmètre S1 (et uniquement S1)

- **Strates temporelles** : 5 années échantillonnées (ex. 2010, 2014, 2018, 2022, 2025). L'année est la variable explicative principale.
- **Strates disciplinaires** : 4 domaines aux cultures de partage très différentes — biologie/médecine, informatique, sciences sociales, physique/astronomie. L'écart entre disciplines est le second chiffre le plus intéressant.
- **Volume S1** : ≥ 2 000 articles échantillonnés aléatoirement par strate croisée, à partir d'OpenAlex, restreints aux articles en accès ouvert dont le texte intégral est accessible.
- **Types de liens suivis** : dépôts de code (GitHub, GitLab, Bitbucket, Software Heritage), dépôts de données (Zenodo, Figshare, Dryad, OSF, dépôts institutionnels), DOI de jeux de données, URL brutes.

**Hors périmètre S1** — ne pas commencer, ne pas « juste poser les bases » : site public, classement d'éditeurs nominatif, API, alertes, articles sous paywall, analyse du *contenu* des dépôts, corrélation avec les citations.

---

## 4. Les cinq pièges qui tuent le projet

C'est ici que se joue la valeur. Tout le reste est de la plomberie.

**1. Le code HTTP ment.** Un `200` peut être une page « dépôt introuvable ». Un `403` peut être Cloudflare, pas une suppression. Un `429` est un échec du crawler, pas du lien. Traitement obligatoire :
- Pour les hébergeurs à API (GitHub, GitLab, Zenodo, Figshare, OSF, DataCite, Crossref) : **interroger l'API, jamais le HTML**. L'API répond sans ambiguïté sur l'existence.
- Pour le reste : détection de soft-404 par heuristiques déterministes (comparaison avec la réponse d'une URL volontairement inexistante sur le même domaine — technique classique, sans annotation).
- Trois tentatives, **espacées de plusieurs jours**, jamais dans la même minute. Un lien n'est déclaré mort qu'après échec sur trois dates distinctes.

**2. Quatre états, jamais deux.** `alive` / `dead` / `restricted` (existe mais accès contrôlé — cas légitime, fréquent en médecine) / `unknown` (le crawler a échoué). `unknown` n'entre **jamais** dans le dénominateur d'un taux publié ; il est compté et reporté à part. Un échec de crawl converti en « lien mort » est une falsification — c'est l'erreur qui détruirait le projet.

**3. Mort ≠ n'a jamais existé.** Un lien typographiquement cassé dès la publication est une catégorie différente d'un lien qui a fonctionné puis disparu. Les séparer dès le schéma. La deuxième catégorie est la vraie mesure de rot ; la première est une mesure de contrôle éditorial, tout aussi intéressante mais à ne pas mélanger.

**4. « Disponible sur demande » n'est pas un lien.** C'est une catégorie à part, connue pour échouer en pratique, et qu'il serait malhonnête de compter comme un lien mort ou comme un lien vivant. Elle est comptée séparément et le rapport dit qu'elle n'a pas été testée — on ne va pas écrire à des milliers d'auteurs.

**5. Être un citoyen correct du réseau.** Respect de `robots.txt`, limitation de débit agressive à la baisse, `User-Agent` portant un contact et l'URL du projet, respect strict des quotas d'API, aucun contournement de protection. Un observatoire qui matraque les dépôts scientifiques est mort à la naissance, et méritoirement. Si un hébergeur demande l'arrêt, on s'arrête et on le dit dans le rapport.

---

## 5. Architecture

```
artifact-rot/
  PLAN.md                     ← ce fichier
  pyproject.toml              ← uv, Python 3.12
  artifact_rot/
    sample.py                 ← échantillonnage stratifié depuis OpenAlex, graine fixée
    fulltext.py               ← récupération du texte intégral (sources ouvertes uniquement)
    extract/
      statements.py           ← repérage des sections de disponibilité
      links.py                ← extraction URL / DOI / identifiants
      normalize.py            ← canonicalisation, déduplication
    probe/
      base.py                 ← Prober(ABC) : check(link) -> Status
      api_github.py / api_zenodo.py / api_osf.py / api_doi.py
      http_generic.py         ← soft-404 par sonde de contrôle
    schedule.py               ← 3 passes espacées, file persistante, reprise
    survival.py               ← courbe de survie par âge, IC Wilson, demi-vie
    report.py
  data/sample/                ← échantillon figé, graine et requête versionnées
  runs/                       ← <ISO8601>-<git_sha>/ jamais écrasé
  tests/
```

### Contrats

```python
class Link(BaseModel):
    paper_doi: str
    paper_year: int
    discipline: str
    publisher: str
    raw: str                        # tel qu'écrit dans l'article
    normalized: str
    kind: Literal["code_repo","data_repo","dataset_doi","generic_url","on_request"]
    host: str
    malformed_at_source: bool       # piège 3

class Probe(BaseModel):
    link_id: str
    probed_at: datetime
    method: Literal["api","http"]
    status: Literal["alive","dead","restricted","unknown"]
    evidence: dict                  # code, corps tronqué, réponse d'API
    attempt: int                    # 1..3
```

### Règles techniques
- Un run est immuable : `runs/<ISO8601>-<git_sha>/`, jamais écrasé, jamais nettoyé.
- L'échantillon est figé et versionné : graine, requête OpenAlex, date d'extraction. Un échantillon non reproductible rend tout le reste invérifiable.
- Statut final d'un lien = fonction déterministe de ses 3 sondes, définie dans le code et documentée. Pas de jugement au cas par cas.
- Toute preuve conservée : sans le corps de réponse tronqué, une contestation est impossible à arbitrer.

---

## 6. La métrique qui porte le projet

Le taux brut de liens morts est banal et sera contesté sur l'échantillonnage. La métrique qui tient, et qui est le vrai livrable :

**La demi-vie d'un lien d'artefact de recherche** — le temps au bout duquel la moitié des liens ne résout plus, estimée par courbe de survie (Kaplan-Meier), déclinée par type d'hébergeur, par discipline, par éditeur.

Elle est supérieure au taux brut pour trois raisons : elle absorbe les différences d'échantillonnage entre strates, elle se compare d'une année sur l'autre, et elle se dit en une phrase mémorisable. C'est le chiffre qui circule — et il est honnête, ce qui est la condition pour qu'il tienne quand il circulera.

Corollaire de conception : le schéma de données doit permettre la censure à droite dès le départ (un lien encore vivant aujourd'hui est une observation censurée, pas un succès définitif). Prévu maintenant, pas rattrapé après.

---

## 7. Étapes d'exécution

Ordre strict. Aucune étape entamée avant que la précédente passe son critère.

| # | Étape | Sortie | Critère de passage |
|---|---|---|---|
| E0 | Veille : lire `metacheck`, vérifier qu'aucun observatoire équivalent n'existe, relever les études ponctuelles existantes pour pouvoir s'y comparer | `docs/etat-de-lart.md` | Rien d'équivalent en continu, ou pivot décidé |
| E1 | Échantillonnage stratifié, figé, reproductible | `data/sample/` | Rejouer la graine redonne le même échantillon |
| E2 | **Sondes + classification** (§4) | code + tests | Sur un jeu de contrôle de 200 liens dont l'état est connu **par construction** (URL fabriquées : existantes, supprimées, privées, malformées), classification correcte ≥ 98 % |
| E3 | Extraction des liens depuis le texte intégral | code + tests | Rappel vérifié sur un sous-ensemble où les liens sont déjà connus via métadonnées structurées |
| E4 | Ordonnanceur 3 passes, file persistante | code | Passe à blanc complète sans dépasser les quotas |
| E5 | Run officiel S1 (3 passes, ≥ 2 semaines calendaires) | `runs/…` | Taux d'`unknown` < 5 %, aucun hébergeur en rate-limit soutenu |
| E6 | Survie, demi-vie, analyse contre le critère §2 | `report.md` + figures | Verdict H1 écrit **avant** toute mise en forme |
| E7 | Décision | — | Suivi continu, ou publication du négatif et arrêt |

**E2 est le test de santé du projet.** Le jeu de contrôle se fabrique sans annotation : on crée soi-même des dépôts publics, on en supprime, on en passe en privé, on fabrique des URL malformées. On connaît la vérité par construction — exactement le même principe que celui qui fonde le projet entier. Si la classification n'atteint pas 98 % là-dessus, aucun chiffre produit ensuite ne vaut rien.

---

## 8. Budget et friction

- **Coût monétaire** : zéro, hors nom de domaine éventuel. OpenAlex, Crossref, DataCite, les API GitHub/Zenodo/OSF : toutes gratuites. Pas de GPU, pas d'annotateur, pas d'accès privilégié.
- **Coût réel** : le **temps calendaire**. Les trois passes espacées imposent ≥ 2 semaines entre le premier et le dernier sondage. Ce n'est pas du travail, c'est de l'attente — à lancer tôt et à laisser tourner pendant qu'on fait autre chose. C'est la friction de Clausewitz sous sa forme la plus bénigne : prévisible et gratuite si elle est anticipée, coûteuse si on la découvre à la fin.
- **Piège de dispersion** : la tentation sera d'ajouter des disciplines, des années, des types de liens. Chaque ajout retarde le premier chiffre publié sans le renforcer. Le périmètre §3 est fermé jusqu'à E7.

---

## 9. Ligne éditoriale du rapport (E6)

- Le verdict s'écrit avant les figures, avant le titre, avant toute mise en forme.
- **On mesure des résolutions, pas des intentions.** Chaque affirmation est de la forme « sur N liens extraits d'articles de l'année A, M ne résolvaient pas au terme de trois sondages entre telle et telle date ». Jamais « les chercheurs de tel domaine ne partagent pas ».
- **Aucun auteur nommé, jamais.** Les agrégats portent sur des éditeurs, des revues, des disciplines, des hébergeurs — des institutions, qui ont des politiques. Un individu n'a pas de politique, il a un serveur qui est tombé.
- Les limites sont listées par nous, en premier, exhaustivement : restriction à l'accès ouvert, extraction imparfaite, liens non testés de la catégorie « sur demande », `restricted` distinct de `dead`, fenêtre de sondage courte, biais d'échantillonnage d'OpenAlex.
- Méthode, code, échantillon et preuves publiés **en même temps** que les chiffres.
- Le titre porte la demi-vie, pas l'indignation. Un chiffre simple circule ; les nuances du corps de texte sont ce qui le fait tenir quand il circule.

---

## 10. Ce qui n'est pas ce projet

On ne construit pas un outil de détection de fraude, pas un service de vérification vendu aux revues, pas un archiveur, pas un classement moral. On mesure une chose, correctement, on la publie, on recommence dans six mois. Le reste vient après S1 — ou ne vient pas.
