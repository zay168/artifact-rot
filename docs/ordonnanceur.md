# E4 — L'ordonnanceur des trois passes

> Critère de passage (PLAN.md §7) : **passe à blanc complète sans dépasser les quotas.**
> **Tenu au 2026-09-20** : 2 363 liens dus, 2 363 traités, aucun quota dépassé, durée estimée
> 1,16 h.

---

## 1. Pourquoi une base de données et pas un script

Le coût du projet n'est pas le calcul, c'est le **temps calendaire** (§8). Trois sondes espacées
d'au moins dix jours imposent deux semaines entre la première et la dernière.

L'ordonnanceur doit donc survivre à tout : une coupure réseau, un redémarrage, un portable fermé
pendant douze jours. D'où une file **SQLite** en mode WAL, `synchronous=FULL` : chaque sonde est
écrite sur disque dès son retour, et reprendre revient à relancer la même commande.

Deux tests couvrent cette promesse — recharger la file n'efface aucune sonde, et fermer puis
rouvrir la base retrouve l'état exact.

## 2. Une économie assumée : on arrête de sonder un lien vivant

La règle de résolution (§5) dit qu'une seule observation vivante l'emporte. Sonder deux fois de
plus un lien déjà vu vivant n'ajoute rien à son statut, et représente l'essentiel du trafic.

Conséquences, toutes assumées :

- le trafic imposé aux hébergeurs chute d'environ **80 %** — c'est le §4, piège 5 ;
- un lien qui meurt entre la passe 1 et la passe 3 est compté vivant. La mesure est donc
  **conservatrice** : elle sous-estime la mortalité, jamais l'inverse ;
- les trois sondes restent obligatoires pour déclarer un lien mort, **sans exception**.

## 3. Un budget est un débit, pas un plafond

Première version : une passe s'arrêtait dès qu'un hôte avait reçu son quota, et abandonnait le
reste des liens en silence. C'est faux, et c'était pire que faux — c'était silencieux.

Une passe qui demande 2 919 résolutions de DOI avec un budget de 1 000 à l'heure n'est pas une
passe interdite : c'est **une passe de trois heures**. L'ordonnanceur espace donc les requêtes de
`3600 / budget` secondes par hôte, et la passe dure le temps qu'il faut.

Les budgets sont volontairement **en dessous** des limites annoncées : GitHub authentifié permet
5 000 requêtes à l'heure, on en prend 2 000. On ne joue pas au plus près d'un quota chez quelqu'un
d'autre.

| hôte | débit retenu |
|---|---|
| `api.github.com` | 2 000 / h |
| `doi.org` | 1 000 / h |
| `api.bitbucket.org` | 500 / h |
| `gitlab.com`, `zenodo.org`, `api.osf.io`, `api.figshare.com` | 300 / h |
| `archive.softwareheritage.org` | 100 / h |
| tout autre hôte | 200 / h |

Le plan compte le **pire cas**, pas la moyenne : un lien GitHub en 404 déclenche jusqu'à trois
requêtes (dépôt, propriétaire, Software Heritage). Un budget calculé sur une moyenne est un budget
dépassé un jour sur deux.

## 4. Ce qu'on sonde, et surtout ce qu'on ne sonde pas

C'est ici que l'étape a produit le plus de valeur. La file brute contenait **7 959 liens** extraits
de 400 articles. Après filtrage : **2 363**. Les 5 596 écartés l'ont été pour quatre raisons, toutes
mesurées.

| écarté | n | pourquoi |
|---|---|---|
| `citation_doi` | 3 392 | DOI d'un article cité, pas un artefact |
| hôte bibliographique | 1 688 | PubMed, arXiv, Scholar… une citation, pas un artefact |
| `malformed_at_source` | 264 | cassé dès la publication : rien à sonder (piège 3) |
| référence non-artefact | 252 | lien du corps de bibliographie vers autre chose qu'un dépôt |

### 4.1 Le plus important : tout DOI n'est pas un DOI de jeu de données

**Écart assumé au PLAN.md §5.** Le plan liste `dataset_doi` parmi les types suivis. Sans
distinction supplémentaire, ce type absorbait **tout** DOI rencontré : 3 449 liens sur 8 073.

L'immense majorité sont des DOI d'articles cités en bibliographie. Les sonder aurait produit un
taux de survie excellent et hors sujet — **un DOI d'article est maintenu par son éditeur, il ne
meurt pas** — tout en infligeant des milliers de requêtes inutiles à `doi.org`.

D'où un type supplémentaire, `citation_doi`, exclu du sondage. La liste de préfixes reconnus comme
dépôts de données (`10.5281` Zenodo, `10.6084` Figshare, `10.17605` OSF, `10.7910` Dataverse…) est
volontairement **conservatrice** : dans le doute, un DOI est une citation. Un dépôt manqué est une
perte ; un article compté comme jeu de données est une faute.

### 4.2 Les serveurs de prépublication sont des citations

arXiv, bioRxiv, medRxiv, SSRN, HAL : 556 liens arXiv dans 400 articles, presque tous des
citations. Un lien arXiv désigne un **article**, pas un artefact de code ou de données.

### 4.3 Les liens cassés ne sont jamais sondés

Piège 3. Un lien malformé n'a jamais pu fonctionner : il n'y a rien à sonder, et le résultat serait
indiscernable d'un lien mort. Il est compté à part, comme mesure du contrôle éditorial.

### 4.4 Ce qui est gardé malgré la provenance

Un lien de **bibliographie qui pointe vers un dépôt** reste sondé. C'est exactement le cas mesuré
par metacheck (issue #411), où 3 % des articles ne citent leur dépôt que là. Les exclure en bloc
perdrait ces cas.

Et le NCBI reste sondé quand l'URL désigne des données (`/nuccore/`, `/sra/`, `/geo/`…) et non une
notice PubMed.

## 5. La démonstration de fin

Passe réelle sur 60 liens, avec jeton GitHub :

```
statuts : {'alive': 35, 'unknown': 18, 'dead': 7}
```

Puis l'état de la file :

```
statuts resolus : {'alive': 35, 'unknown': 25}
```

**Les 7 sondes `dead` ne produisent aucun lien mort.** Elles deviennent `unknown`, parce qu'une
seule observation ne suffit pas : il en faut trois, sur trois dates distinctes espacées d'au moins
dix jours.

C'est le §4 piège 2 en action, vérifiable sur une sortie réelle plutôt que sur une promesse.

## 6. Commandes

```bash
export ARTIFACT_ROT_CONTACT="vous@exemple.org"
export GITHUB_TOKEN="ghp_..."

uv run python -m artifact_rot.schedule load runs/<...>/links.jsonl
uv run python -m artifact_rot.schedule plan        # ce que la prochaine passe ferait
uv run python -m artifact_rot.schedule dryrun      # passe a blanc, sans reseau
uv run python -m artifact_rot.schedule run [n]     # passe reelle, n liens au plus
uv run python -m artifact_rot.schedule status
```

`run` est interruptible et reprenable : relancer la même commande continue où la passe s'était
arrêtée.

## 7. Ce qui reste avant E5

- **Reconstruire le cache de textes intégraux.** Celui utilisé ici a été constitué avant la
  correction du classement des localisations : les hôtes `nih.gov`, `hhs.gov`, `usa.gov` et
  `about.zenodo.org` qui apparaissent dans la file sont l'habillage de pages de notice, pas des
  liens d'articles.
- **Agrandir le sous-échantillon.** 400 articles donnent 86 liens de dépôt seulement.
- **Porter la famille `restricted` du jeu de contrôle à six ou dix entrées** (E2).
- **Une console Windows est en cp1252** : l'affichage a été forcé en UTF-8 après qu'un nom d'hôte
  cyrillique du corpus a fait tomber un rapport en fin de traitement. Le rapport ne doit jamais
  être ce qui casse un run.
