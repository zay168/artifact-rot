# Prolongation S1 — recentrage sur les artefacts, écrit avant la collecte

> Écrit le 2026-10-04, **après** le verdict des trois passes et **avant** toute collecte
> supplémentaire. Le commit qui introduit ce fichier précède le moissonnage : l'historique git en
> fait foi.

## 1. Ce qui s'est passé

Les trois passes (21 sept., 26 sept., 4 oct. 2026) sur 3 988 liens issus de 1 496 articles ont
donné, critère du §2 appliqué sans retouche (`runs/20261004T014500Z-verdict/`) :

| | Mesuré | Seuil | |
|---|---|---|---|
| Taux de non-résolution, strate 2018 | 33,1 % (IC 29,4–37,0) | > 20 % | tenu |
| Écart 2010 – 2025 | 7,8 pts (IC 2,3–13,4) | > 15 pts | non tenu |

Verdict : **zone grise**. Le §2 autorise une extension, une seule, à un facteur 3.

## 2. Deux constats qui changent ce que l'extension doit mesurer

**Le chiffre ne porte pas sur l'objet du projet.** 95 % des liens sondés sont des `generic_url`
cités dans le corps du texte (who.int, cdc.gov, youtube.com…). Les liens vers du code et des
données — l'objet du §1 — ne sont que 177. Le taux de 33 % mesure la disparition des références
web, phénomène déjà documenté, pas celle des artefacts.

**Le critère E5 est inatteignable sur les URL génériques.** 22,8 % d'`unknown`, contre < 5 %
exigés. Les causes sont des pare-feu (263), des `robots.txt` (176), des échecs de connexion et
des délais (271). Les deux premières sont permanentes et le §4 interdit de les contourner.

## 3. Ce que nous savons déjà — déclaré pour ne pas le cacher

Sur les 177 liens d'artefacts déjà sondés trois fois : 6 % des dépôts de code et 1 % des dépôts
de données ne résolvent pas. Le recentrage est donc décidé **en connaissant** un signal qui va
vers la réfutation de H1 sur ce périmètre. C'est l'inverse d'un recentrage opportuniste : il
rapproche le projet d'un résultat négatif, pas d'un résultat spectaculaire. On le dit quand même.

## 4. Ce qui est fixé maintenant, avant la collecte

1. **Périmètre de l'analyse principale** : `kind ∈ {code_repo, data_repo, dataset_doi}`. Les
   `generic_url` déjà mesurées sont publiées à part, avec leur verdict « zone grise », jamais
   fondues dans le chiffre principal.
2. **Extension ×3, la seule autorisée** : de 100 à 300 articles par strate croisée (2 000 → 6 000),
   pris dans l'échantillon E1 déjà figé (40 000 articles). Les 200 nouveaux par strate sont tirés
   parmi les articles non encore moissonnés, graine `20261004`. Aucun nouveau tirage OpenAlex.
3. **Seuls les liens d'artefacts des nouveaux articles sont sondés.** Sonder des milliers d'URL
   génériques qui ne servent plus l'analyse principale serait une charge inutile sur les serveurs
   d'autrui (§4, piège 5).
4. **Critère H1 inchangé, mot pour mot** : taux > 20 % sur 2018, et écart le plus ancien – le plus
   récent > 15 pts, IC 95 % excluant 0 sur les deux. Même code (`verdict_h1`), même règle de
   résolution (trois échecs sur trois dates espacées d'au moins 10 jours).
5. **Pas de seconde extension.** Si le résultat est encore en zone grise, on publie la zone grise.
6. **Critère E5** apprécié sur le périmètre artefacts, où les sondes passent par des API.

## 5. Limites connues dès maintenant

- Rappel de l'extraction sur les liens de dépôt : 0,54 (E3). Un lien d'artefact sur deux n'est
  pas extrait. Aucun indice que ce rappel dépende de l'année ; à vérifier sur l'extension.
- Les dépôts institutionnels sont classés `generic_url` par l'extracteur et sortent donc du
  périmètre. Le taux publié porte sur les hébergeurs reconnus.
- Effectif attendu : environ 530 liens d'artefacts, une centaine par année. Intervalles larges
  par strate ; les déclinaisons par discipline seront indicatives.

## 6. Calendrier

Passe 1 de l'extension le 2026-10-04 ; passe 2 à partir de J+5 ; passe 3 à partir de J+10 ;
verdict le soir de la passe 3.
