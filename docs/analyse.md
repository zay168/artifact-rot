# E6 — L'analyse, écrite avant les chiffres

> Écrit le 2026-09-21, **avant les passes 2 et 3**, donc avant d'avoir vu le moindre résultat
> final. Le §2 du plan exige que le critère de décision soit fixé avant le premier run ; ce
> document et `artifact_rot/survival.py` en sont la traduction exécutable.

Une analyse écrite après coup peut toujours être ajustée, même de bonne foi, jusqu'à ce qu'elle
dise ce qu'on espérait. Écrite avant, elle ne le peut plus.

---

## 1. Un écart au PLAN.md §6, et c'est le point important

**Le plan prescrit Kaplan-Meier. Kaplan-Meier ne s'applique pas à ces données.**

Kaplan-Meier suppose qu'on observe, pour chaque sujet, **soit sa date de mort, soit la date à
laquelle on l'a vu vivant pour la dernière fois**.

Ce n'est pas ce qu'on observe. On regarde, à un instant unique, des liens issus d'articles d'âges
différents, et on note pour chacun : vivant ou mort **aujourd'hui**. Pour un lien d'un article de
huit ans, on sait seulement :

- s'il est mort → il est mort quelque part entre 0 et 8 ans. Rien de plus.
- s'il est vivant → il a survécu au moins 8 ans.

C'est ce que la littérature appelle des **données de statut courant** (interception à un instant,
ou censure par intervalle de cas 1). L'estimateur non paramétrique adapté n'est pas Kaplan-Meier
mais la **régression isotone** de la proportion de morts en fonction de l'âge — équivalente ici à
l'estimateur de Turnbull, obtenue par l'algorithme de regroupement des violations adjacentes
(PAVA).

**Ce que Kaplan-Meier aurait produit** : en lui donnant ces données, on lui affirme implicitement
que chaque lien mort est mort le jour de la publication de son article. La courbe obtenue serait
systématiquement trop pessimiste — et rien dans sa forme ne le signalerait. Elle aurait l'air
parfaitement normale.

C'est exactement le genre d'erreur que le §0 appelle un boomerang : le projet mesure la rigueur
d'autrui, et publierait une courbe de survie mal spécifiée.

**Ce que la régression isotone apporte en plus** : elle impose que la survie décroisse avec l'âge.
Si le bruit d'échantillonnage fait remonter une strate — 2014 mieux servie que 2018 — elle regroupe
les deux plutôt que de publier une courbe qui remonte. Une survie qui augmente avec l'âge est
impossible ; l'afficher serait présenter un artefact d'échantillonnage comme un résultat.

**Quand le plan redeviendra applicable** : dès que le projet aura deux campagnes espacées de six
mois, les données deviendront réellement censurées par intervalle avec des bornes connues, et
Turnbull s'appliquera sous sa forme générale. Kaplan-Meier ne s'appliquera toujours pas.

## 2. Ce qui n'entre jamais dans un dénominateur

**`unknown`.** Jamais, sous aucun prétexte (§4, piège 2). Compté et reporté à part. C'est testé.

**`restricted`** est plus délicat : la ressource existe, elle ne résout simplement pas en accès
libre. Le calcul principal la compte **vivante** — c'est ce qu'elle est, au sens de l'existence.

Une variante qui l'exclut entièrement du dénominateur est calculée en même temps et publiée à
côté, parce que le choix est discutable et qu'un lecteur doit pouvoir voir ce qu'il change.

## 3. La demi-vie n'est jamais extrapolée

Si la courbe ne descend pas sous 0,5 sur la plage observée, la fonction rend **`None`**, pas un
nombre.

C'est le chiffre que tout le monde citera. Le produire par extrapolation au-delà de la strate la
plus ancienne serait l'inventer. « La demi-vie dépasse N ans » est une information ; un nombre
extrapolé n'en est pas une.

## 4. Le verdict sur H1, codé mot à mot

Le §2 dit :

> **H1 tenue** si le taux de liens non résolus dépasse `20 %` sur la strate 2018, **et** si l'écart
> entre la strate la plus ancienne et la plus récente dépasse `15 points`, IC 95 % (Wilson)
> excluant 0 sur les deux.
> **H1 réfutée** si le taux reste sous 20 % partout **ou** si l'effet d'âge est nul.
> Zone grise : élargir l'échantillon **une seule fois**, à un facteur 3.

`verdict_h1()` ne prend aucune décision qui ne soit pas dans ces trois phrases.

### Un « ou » lu comme un « et » — corrigé avant la mesure

La première version exigeait, pour réfuter, que le taux soit bas **et** que l'effet d'âge soit nul.
Le plan écrit « ou ».

La différence n'est pas cosmétique. Avec « et », un monde où les liens meurent beaucoup mais sans
aucun rapport avec l'âge aurait été classé « zone grise », ce qui aurait justifié d'élargir
l'échantillon — c'est-à-dire de continuer à chercher.

Or H1 affirme **deux choses à la fois**, dont que « le taux de mort croît nettement avec l'âge ».
Sans effet d'âge, H1 est fausse, quel que soit le taux. Et le plan impose alors de publier et de
s'arrêter.

Autrement dit, l'erreur allait dans le sens qui fait continuer le projet plutôt que dans celui qui
l'arrête. C'est la direction dans laquelle un biais passe le plus facilement inaperçu.

### Ce qui reste une vraie zone grise

Un seul cas : les deux signaux existent, mais l'un n'atteint pas son seuil — par exemple un taux
de 25 % et un effet d'âge réel de 10 points seulement. Là, élargir l'échantillon peut trancher.

### L'intervalle porte sur la différence, pas sur deux proportions

Le §2 demande que l'écart entre strates dépasse 15 points « IC excluant 0 ». C'est un intervalle
sur une **différence** qu'il faut (méthode de Newcombe), pas deux intervalles séparés : deux
intervalles qui se chevauchent légèrement peuvent correspondre à une différence significative, et
l'erreur inverse est encore plus fréquente.

## 5. Comment l'analyse a été validée sans données réelles

Même procédé que le jeu de contrôle E2, appliqué à la statistique : **on fabrique un monde dont on
connaît la demi-vie, on fait tourner l'estimateur dessus, et on vérifie qu'il retrouve le nombre.**

`tests/test_survival.py` génère des mondes de demi-vie 3, 5, 8 et 12 ans, observés exactement comme
le projet observe le sien — un instant unique, des strates d'âges différents. L'estimateur doit
retrouver la demi-vie à 15 % près.

Sont également vérifiés, sur des cas construits :

- `unknown` n'entre jamais au dénominateur ;
- la courbe de survie est toujours décroissante ;
- une demi-vie hors plage rend `None` et non un nombre ;
- les quatre verdicts possibles, chacun sur un monde qui l'appelle ;
- un petit effectif ne suffit pas à tenir H1, même avec un taux de 40 % — c'est précisément ce que
  l'intervalle de confiance est là pour empêcher.

## 6. Ce qui manque encore

- Le **taux d'indétermination** est à 26 % après la passe 1, quand E5 en exige moins de 5 %. Il est
  porté par `H1Result.unknown_rate` et devra être publié en tête du rapport, pas en note.
- Les déclinaisons **par hébergeur, par discipline, par éditeur** (§6) utilisent les mêmes
  fonctions, sur des sous-ensembles. Rien de nouveau à écrire, mais les effectifs par croisement
  seront faibles et les intervalles larges : à publier avec leurs intervalles, jamais seuls.
- `report.py` — la mise en forme. Elle vient **après** le verdict, jamais avant (§9).
