# E1 — L'échantillon

> Critère de passage (PLAN.md §7) : **rejouer la graine redonne le même échantillon**.
> **Tenu au 2026-09-20** : intégrité du fichier vérifiée, indice de Jaccard moyen de **1,0** sur
> les vingt strates après rejeu complet de la requête.

---

## 1. Ce qui a été tiré

40 000 articles, 2 000 par strate croisée, graine `20260920`.

| | 2010 | 2014 | 2018 | 2022 | 2025 |
|---|---|---|---|---|---|
| Médecine (OpenAlex `fields/27`) | 2 000 | 2 000 | 2 000 | 2 000 | 2 000 |
| Informatique (`fields/17`) | 2 000 | 2 000 | 2 000 | 2 000 | 2 000 |
| Sciences sociales (`fields/33`) | 2 000 | 2 000 | 2 000 | 2 000 | 2 000 |
| Physique / astronomie (`fields/31`) | 2 000 | 2 000 | 2 000 | 2 000 | 2 000 |

Filtres appliqués, identiques sur toutes les strates :
`open_access.is_oa:true`, `has_fulltext:true`, `type:article`.

Composition obtenue : **9 211 éditeurs distincts**, **15 903 revues distinctes**. Les cinq
premiers éditeurs — Elsevier (2 418), IOP (1 394), Springer (1 249), Wiley (1 114), MDPI (1 080) —
pèsent 18 % de l'échantillon. Statut d'accès ouvert : diamond 12 067, bronze 9 753, gold 6 851,
green 6 187, hybrid 5 142.

Les 40 000 articles ont tous une URL de texte intégral. Il n'y a donc pas d'attrition à ce stade
— celle d'E3 viendra de l'extraction, pas de la disponibilité.

## 2. Deux mécanismes de reproductibilité, à ne pas confondre

**La graine.** `sample=N&seed=S` d'OpenAlex renvoie le même tirage à requête identique. Vérifié le
2026-09-20 : deux appels successifs, mêmes identifiants, même ordre, sur les vingt strates.

**Le gel sur disque.** La graine ne suffit pas, parce que la *population* interrogée bouge :
OpenAlex indexe en continu, corrige des métadonnées, et son indicateur `has_fulltext` évolue.
Rejouer la même requête dans six mois peut donc donner un autre tirage sans qu'aucun bug ne soit
en cause.

**L'échantillon officiel est le fichier**, `data/sample/<horodatage>-seed<graine>/sample.jsonl`,
accompagné d'un manifeste portant la requête exacte de chaque strate, la graine, la date
d'extraction et l'empreinte SHA-256.

`verify` contrôle les deux séparément :

- **intégrité** — le fichier correspond-il à son empreinte ? Un échec est toujours une erreur ;
- **dérive** — rejouer la requête aujourd'hui redonne-t-il les mêmes identifiants ? Un écart est
  une information sur OpenAlex, mesurée et reportée, jamais corrigée en silence.

## 3. Deux décisions prises à cette étape

### 3.1 Pas de filtre sur la présence d'un DOI — et c'est important

Le contrat du §5 donne `paper_doi: str` comme clé d'un lien. La mesure sur l'échantillon montre
que **la part d'articles sans DOI dans OpenAlex est fortement corrélée à l'âge** :

| part sans DOI (%) | 2010 | 2014 | 2018 | 2022 | 2025 |
|---|---|---|---|---|---|
| Sciences sociales | **31,2** | 26,2 | 12,8 | 2,2 | 4,8 |
| Informatique | **22,6** | 15,6 | 11,8 | 1,9 | 2,2 |
| Physique / astronomie | 7,3 | 5,1 | 5,0 | 1,4 | 2,2 |
| Médecine | 5,7 | 3,3 | 2,3 | 0,7 | 1,2 |

Ajouter `has_doi:true` aurait retiré près d'un tiers de la strate la plus ancienne en sciences
sociales contre 2 % de la plus récente. Le filtre aurait donc introduit **un biais de sélection
porté par la variable explicative principale du projet** — exactement le genre de choix qui
produit un effet d'âge sans que l'âge y soit pour rien.

Décision : la clé devient l'identifiant OpenAlex (`W…`), présent sur 100 % de l'échantillon. Le DOI
reste porté quand il existe, parce que c'est lui qui parle aux éditeurs et aux lecteurs. Écart au
§5 assumé, écrit dans `models.py` au point où il se constate.

### 3.2 « Médecine » plutôt que « biologie/médecine »

Le plan dit « biologie/médecine ». Le champ OpenAlex le plus proche est `Medicine` (27).
`Biochemistry, Genetics and Molecular Biology` (13) serait l'autre choix défendable, et plus proche
de « biologie ».

Médecine est retenu parce que c'est la culture où « disponible sur demande » domine — le cas que le
piège 4 doit précisément savoir compter à part. Le choix est fermé jusqu'à E7. Il est inscrit ici
pour être contestable : quelqu'un qui referait le tirage avec `fields/13` obtiendrait
vraisemblablement un taux de partage plus élevé, et ce serait un résultat en soi.

## 4. Un défaut attrapé par le critère, pas par la relecture

La première version du code paginait le tirage **par curseur**, comme l'impose la documentation
d'OpenAlex pour parcourir de gros jeux. Sous `sample=`, l'API renvoie `next_cursor: null` dès la
première page : le curseur ne pagine pas un tirage.

Résultat : 200 articles par strate au lieu de 2 000, **sans aucune erreur levée**. Le code
fonctionnait, il ramenait simplement dix fois moins que demandé.

Deux corrections :

- pagination classique `page=`, vérifiée sur l'API — pages disjointes, et le même couple
  (graine, page) redonne exactement la même page ;
- `build` compare désormais l'obtenu au demandé pour chaque strate, affiche les strates
  incomplètes et **sort en code 1**. Un tirage court doit être bruyant.

C'est la démonstration de l'utilité d'un critère de passage chiffré : « rejouer la graine redonne
le même échantillon » aurait été satisfait par les 200 articles. « 2 000 par strate » ne l'était
pas.

## 5. Limites à reporter en E6

À lister par nous, en premier, comme l'impose le §9 :

- **Restriction à l'accès ouvert.** Le périmètre exclut les articles sous paywall (§3). Le taux
  mesuré ne vaut que pour l'OA, et rien ne dit que les pratiques y sont représentatives.
- **`has_fulltext` est un indicateur d'OpenAlex**, pas une garantie que le texte soit exploitable.
  L'attrition réelle se mesurera en E3.
- **Biais d'indexation d'OpenAlex.** La couverture est plus fine sur le récent et sur l'anglophone.
  L'écart de DOI manquants ci-dessus en est une manifestation directe et mesurée.
- **Un champ par discipline.** Un article interdisciplinaire n'est compté que dans son
  `primary_topic`. Les frontières sont celles d'OpenAlex, pas les nôtres.
- **2025 est une strate jeune.** Une partie de ses articles a moins d'un an ; l'indexation OA y est
  encore incomplète et continuera de s'enrichir après le gel.

## 6. Commandes

```bash
export ARTIFACT_ROT_CONTACT="vous@exemple.org"

uv run python -m artifact_rot.sample build      # tirage, gel, manifeste
uv run python -m artifact_rot.sample verify     # integrite + derive de population
```

`build` écrit un répertoire horodaté et met à jour le pointeur `data/sample/LATEST`. Il n'écrase
jamais un échantillon existant.
