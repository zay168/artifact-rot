# E2 — Le jeu de contrôle

> Critère de passage E2 (PLAN.md §7) : **classification correcte ≥ 98 %** sur un jeu de contrôle
> dont l'état est connu **par construction**.
> Si ce seuil n'est pas atteint, aucun chiffre produit ensuite ne vaut rien. C'est le test de santé
> du projet, et c'est pour ça que c'est le premier code écrit.

---

## 1. Pourquoi « par construction »

Le projet repose sur une astuce : quand la vérité terrain coûte cher, on déplace l'expérience vers
un terrain où elle se fabrique toute seule. Le jeu de contrôle applique le même principe à
lui-même. Personne n'annote. Chaque cas est vrai pour une raison mécanique, écrite dans le champ
`provenance` de chaque cas et vérifiable sans faire confiance à celui qui a rédigé la liste.

## 2. Les familles

| Famille | n | Comment la vérité est fabriquée | Coût |
|---|---|---|---|
| `dead` | 90 | URL sur un hébergeur réel, dans un espace de noms tiré sur **128 bits aléatoires**. La collision est impossible à toute échelle pratique. | nul |
| `alive` | 16 | Ressources publiques adossées à des organisations pérennes (Linux, CPython, NumPy, GNU, Software Heritage, DOI d'articles publiés). | nul |
| `malformed` | 9 | Invalidité **syntaxique**, évaluée hors ligne. Aucune requête réseau, donc aucune incertitude. | nul |
| `waf` | 2 | Hôte derrière un pare-feu applicatif. La bonne réponse attendue est `unknown`. | nul |
| `restricted` | 24 | Trois sources, voir §2 bis : retraits légaux GitHub (12, **non circulaire**), enregistrements Zenodo restreints (9, partiellement circulaire), ressources possédées par l'auteur (3). | une manipulation, une fois |

## 2 bis. Résultat mesuré au 2026-09-20 (famille `restricted` complétée)

```
jeu de controle E2 — 141 cas — verdict : passe
  alive       n=16   exactitude=0.938  unknown=1
      X alive-012  unknown  transport_timeout  https://osf.io/ezcuj/
  dead        n=90   exactitude=1.000  unknown=0
  malformed   n=9    exactitude=1.000  unknown=0
  restricted  n=24   exactitude=0.958  [dont 9 circulaires ; hors circulaires : 0.933]
      X restricted-000  dead  github_api_404  https://github.com/zay168/Lucid-project
  waf         n=2    exactitude=1.000  unknown=2
```

**139 sur 141, soit 0,9858. Le critère de 98 % est franchi.**

Et cette fois la famille `restricted` pèse assez pour dire quelque chose : **24 cas, dont 15 dont
la vérité ne vient pas de notre propre sonde.**

### Deux sources pour `restricted`, de qualités différentes

**Non circulaire — dépôts GitHub retirés pour raisons légales (12 cas).** La vérité vient du dépôt
public [`github/dmca`](https://github.com/github/dmca), qui archive chaque avis de retrait. Nous
lisons un code HTTP ; le registre archive un document juridique. Les deux sont indépendants. Les
12 sont classés `restricted` par `github_api_451_legal`.

C'est la seule source de vérité `restricted` qui ne demande de posséder quoi que ce soit, et elle
était introuvable jusqu'à ce qu'on cherche du côté du droit plutôt que du côté de la technique.

**Partiellement circulaire — enregistrements Zenodo restreints ou sous embargo (9 cas).** La vérité
vient du champ `access` de l'API Zenodo, que notre sonde lit elle-même. Ces cas vérifient que la
chaîne tient, **pas que la classification est juste**. Le champ `circular` les marque, et le
rapport donne l'exactitude hors circulaires à côté de l'exactitude globale — annoncer 0,958 sans
cette distinction aurait surestimé.

**Possédées par l'auteur (3 cas).** Un dépôt GitHub passé en privé, un projet OSF privé, un dépôt
Zenodo sous embargo jusqu'en 2030.

### Les deux erreurs, et pourquoi elles ne sont pas de même nature

`alive-012` — `https://osf.io/ezcuj/` est revenu en **timeout réseau**, donc `unknown`. Ce n'est
pas une erreur de classification : c'est la réponse correcte quand le crawler échoue (§4, piège 2).
Elle compte comme erreur dans le score parce que le score compare à l'attendu, et c'est bien ainsi
— mais elle mesure l'état du réseau ce jour-là, pas la qualité des sondes.

`restricted-000` — le dépôt GitHub privé est classé `dead`. **C'est l'erreur annoncée avant la
mesure, et elle est irréductible** : l'API GitHub renvoie 404 pour un dépôt privé comme pour un
dépôt supprimé, et aucun appel public ne les distingue.

### Conséquence pour le rapport E6

La limite ne se corrige pas, elle se borne. Le rapport doit publier **le nombre de `dead` GitHub
portant `indistinguishable_private_or_deleted`**, qui majore la population possiblement `restricted`
comptée à tort comme morte. Un lecteur peut alors refaire le calcul dans l'autre sens. C'est la
seule façon honnête de traiter une ambiguïté qu'on ne peut pas lever.

**Fait le 2026-09-20** : la famille est passée de 3 à 24 entrées. Avec n = 3, une seule erreur
déplaçait l'exactitude de 33 points, ce qui la rendait illisible.

### Ce que le premier run réel a corrigé — dans le jeu, pas dans les sondes

Le premier passage a donné 0,938 sur `alive` et 0,889 sur `dead`. Les deux causes étaient des
défauts du jeu de contrôle, pas de la classification :

1. **`openalex.org` répond `403` Cloudflare à un robot.** Les onze cas qui l'utilisaient sont
   revenus `unknown` — ce qui est la **bonne** réponse au regard du §4 (« un `403` peut être
   Cloudflare, pas une suppression »). Les compter comme des erreurs revenait à pénaliser la sonde
   pour avoir refusé de conclure. Ces cas sont devenus la famille `waf`, dont la réponse attendue
   *est* `unknown` : ils vérifient désormais que le crawler ne bascule jamais un blocage en mort.
   Les cas génériques `alive` et `dead` sont passés sur `python.org` et `gnu.org`, qui répondent
   honnêtement.
2. **`https://doi. org/10.7939/…` était classé `malformed` à tort.** Ce n'est pas un lien cassé,
   c'est un lien valide coupé par l'extraction PDF, que `repair_spaced_hosts` recolle — et doit
   recoller. Le compter `malformed` faisait passer une réparation réussie pour un échec. Le cas est
   resté, à sa vraie place, dans `tests/test_normalize.py::TestMetacheckBug2GrobidWhitespace`.

Aucune sonde n'a été modifiée pour faire monter le score. Les deux corrections portent sur des cas
dont l'étiquette attendue était fausse, et le raisonnement est écrit ici pour être contestable.

## 3. La famille `restricted` — comment elle a été constituée

C'était le trou honnête du dispositif. Il est comblé, et la façon dont il l'a été mérite d'être
écrite, parce qu'elle s'est jouée sur une idée et non sur du travail.

`restricted` (la ressource existe mais l'accès est contrôlé) est la catégorie la plus difficile à
classer correctement et la plus coûteuse à se tromper : la confondre avec `dead` gonfle
artificiellement le chiffre principal, exactement dans le sens qui flatte la thèse du projet. Un
jeu de contrôle qui l'omet mesure tout sauf ce qui compte.

**Conséquence encodée dans le code** : `_score()` refuse d'émettre un verdict tant que les quatre
familles ne sont pas présentes. Il rend `verdict: "incomplet"`, jamais un pourcentage global.
Cette règle a son propre test (`test_verdict_non_emis_si_une_famille_manque`).

### Provisionnement, une fois pour toutes

Créer un fichier `data/control/restricted.json` :

```json
[
  {
    "url": "https://github.com/<vous>/<depot-prive>",
    "kind": "code_repo",
    "provenance": "depot GitHub cree puis passe en prive le 2026-09-20 ; possede par l'auteur"
  },
  {
    "url": "https://osf.io/<guid>/",
    "kind": "data_repo",
    "provenance": "projet OSF cree en mode prive le 2026-09-20 ; possede par l'auteur"
  },
  {
    "url": "https://zenodo.org/records/<id>",
    "kind": "data_repo",
    "provenance": "depot Zenodo sous embargo jusqu'en 2030 ; possede par l'auteur"
  }
]
```

Six à dix entrées suffisent : le poids de la famille dans le score global est faible, mais sa
**présence** est la condition du verdict. Le fichier est versionné (les URL sont publiques, seul
l'accès au contenu ne l'est pas).

### Un cas révélateur à inclure absolument

Un **dépôt GitHub créé, rendu public, puis passé en privé**. L'API GitHub renverra `404`, comme
pour un dépôt supprimé — les deux sont indiscernables par voie publique (voir
`probe/api_github.py`). Ce cas sera donc *classé `dead` alors qu'il est `restricted`*, et il
**doit** compter comme une erreur dans le score.

C'est voulu. Ce cas mesure la seule limite structurelle connue des sondes, et il faut qu'elle
apparaisse dans le chiffre plutôt que dans une note de bas de page. Si cette limite fait tomber
l'exactitude sous 98 %, le plan impose de traiter le problème — enrichissement systématique par
Software Heritage (`probe/api_swh.py`), ou reclassement de tous les `404` GitHub en catégorie
propre — pas de retirer le cas du jeu.

## 4. Lancer

```bash
export ARTIFACT_ROT_CONTACT="vous@exemple.org"   # obligatoire : PLAN.md §4, piege 5
export GITHUB_TOKEN="ghp_..."                    # optionnel : 60 req/h -> 5000 req/h
uv run python -m artifact_rot.control
```

Sortie : un tableau par famille et un rapport complet dans
`runs/<horodatage>-control/control.json`, contenant chaque cas, le statut observé, la **raison
nommée** de la classification et la preuve brute. Code de sortie `0` seulement si le verdict est
`passe`.

## 5. Lire le résultat

Trois lectures, dans cet ordre :

1. **`verdict`**. `incomplet` signifie qu'une famille manque — ce n'est pas un échec, c'est un
   travail non fait.
2. **L'exactitude par famille**, jamais seulement la globale. 98 % global avec 60 % sur
   `restricted` est un échec déguisé par le déséquilibre des effectifs.
3. **Le compte d'`unknown`**. Un `unknown` n'est pas une erreur de classification — le §4 l'interdit
   explicitement — mais un taux élevé sur la famille `alive` signale un crawler bloqué, et E5 exige
   moins de 5 % d'`unknown` pour passer.

Chaque erreur listée porte sa raison nommée (`github_api_404`, `soft404_control_similar`,
`http_blocked_by_waf`…). Une erreur sans raison identifiable est un bug du dispositif de contrôle,
à corriger avant de toucher aux sondes.

## 6. Ce que le jeu de contrôle ne mesure pas

À écrire dans le rapport E6, parmi les limites :

- Il mesure la **classification d'un lien**, pas l'**extraction** d'un lien depuis un article.
  C'est E3, avec son propre critère et ses propres régressions (voir `docs/etat-de-lart.md` §2.2).
- Les cas `alive` sont des ressources très visibles, donc bien servies. Un serveur de laboratoire
  lent ou capricieux est sous-représenté — c'est précisément là que la sonde générique est la plus
  fragile. Le taux d'`unknown` du run réel (E5) est le vrai juge de ce point, pas le jeu de contrôle.
- Les cas `dead` sont morts depuis toujours. Un lien mort *récemment*, dont l'hébergeur garde encore
  une page de transition, n'est pas représenté.
