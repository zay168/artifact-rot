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
| `restricted` | ? | **Ne se fabrique pas toute seule.** Il faut posséder une ressource réellement privée ou sous embargo. | une manipulation |

## 2 bis. Résultat mesuré au 2026-09-20

```
jeu de controle E2 — 117 cas — verdict : incomplet
  alive       n=16   exactitude=1.000  unknown=0
  dead        n=90   exactitude=1.000  unknown=0
  malformed   n=9    exactitude=1.000  unknown=0
  waf         n=2    exactitude=1.000  unknown=2
  familles absentes : restricted — verdict non emis
```

**115 cas sur 115 correctement classés sur les familles présentes.** Le verdict reste `incomplet`
et le sera tant que `restricted` n'aura pas été provisionnée : le seuil de 98 % n'a pas de sens
tant que la catégorie la plus difficile est absente.

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

## 3. La famille `restricted` — la seule à provisionner

C'est le trou honnête du dispositif, et il est signalé plutôt que masqué.

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
