# artifact-rot

Mesurer, à grande échelle et en continu, **si les liens vers le code et les données annoncés dans
les articles scientifiques résolvent réellement**, et à quelle vitesse ils meurent.

Le livrable n'est pas un taux brut, c'est **la demi-vie d'un lien d'artefact de recherche** —
estimée par courbe de survie, déclinée par hébergeur, discipline et éditeur. Ce chiffre n'existe
nulle part sous forme publique et rejouable.

## Ce que le projet mesure, et ce qu'il ne mesure pas

Il mesure **des réponses HTTP et des résolutions d'identifiants**. Rien d'autre.

- Mesuré : « au 20 septembre 2026, ce lien ne résout pas ».
- Non mesuré, jamais affirmé : « ces auteurs n'ont pas partagé leurs données ».

Un lien mort peut venir d'une migration d'université, d'un dépôt renommé, d'un serveur en panne ce
jour-là. Le rapport le dit, et mesure quand même — parce que du point de vue du lecteur qui veut
reproduire, le résultat est le même.

**Aucun auteur n'est jamais nommé.** Les agrégats portent sur des institutions, qui ont des
politiques ; un individu n'a pas de politique, il a un serveur qui est tombé.

## État d'avancement

| Étape | État |
|---|---|
| E0 — veille et état de l'art | **fait** — [`docs/etat-de-lart.md`](docs/etat-de-lart.md) ; aucun observatoire continu équivalent |
| E1 — échantillonnage stratifié figé | **passé** au 2026-09-20 : 40 000 articles, 20 strates, Jaccard 1,0 au rejeu ([`docs/echantillon.md`](docs/echantillon.md)) |
| E2 — sondes et classification | **passé** au 2026-09-20 : 139/141, soit 0,9858 pour un seuil à 0,98. `restricted` à 24 cas dont 15 non circulaires ([`docs/jeu-de-controle.md`](docs/jeu-de-controle.md)) |
| E3 — extraction depuis le texte intégral | **mesuré** au 2026-09-20 : rappel textuel 0,495 ; l’extraction prend l’union texte + balisage ([`docs/extraction.md`](docs/extraction.md)). Cache à reconstruire avant E5 |
| E4 — ordonnanceur 3 passes | **passé** au 2026-09-20 : passe à blanc complète 2 363/2 363, aucun quota dépassé ([`docs/ordonnanceur.md`](docs/ordonnanceur.md)) |
| E5 — run officiel S1 | **passe 1 lancée le 2026-09-21.** 7 829 liens, 3 passes espacées de 10 jours. Verdict H1 attendu vers le 2026-10-11 |
| E6 — survie, demi-vie, verdict H1 | à faire |
| E7 — décision | à faire |

Aucune étape ne commence avant que la précédente passe son critère (PLAN.md §7).

## Les quatre états d'un lien

`alive` / `dead` / `restricted` / `unknown`. Jamais deux.

`unknown` — le crawler a échoué — **n'entre jamais au dénominateur d'un taux publié**. Il est compté
et reporté à part. Un échec de crawl converti en « lien mort » est une falsification, et c'est
l'erreur qui détruirait le projet.

Un lien n'est déclaré `dead` qu'après **trois échecs sur trois dates distinctes espacées d'au moins
dix jours**. La règle est une fonction déterministe, nommée dans chaque résultat, et testée
(`tests/test_resolve.py`).

## Être un citoyen correct du réseau

`robots.txt` respecté, débit volontairement bas, quotas d'API respectés, aucun contournement de
protection. Le `User-Agent` porte l'URL du projet et **un contact joignable** : la variable
`ARTIFACT_ROT_CONTACT` est obligatoire et son absence est une erreur bloquante.

Si un hébergeur demande l'arrêt, on s'arrête et on le dit dans le rapport.

## Démarrer

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

uv run pytest                                    # 197 tests hors ligne

export ARTIFACT_ROT_CONTACT="vous@exemple.org"
export GITHUB_TOKEN="ghp_..."                    # optionnel, 60 req/h -> 5000 req/h
uv run python -m artifact_rot.control            # E2, jeu de controle
```

## Reprise, pas réimplémentation

`scienceverse/metacheck` (R, AGPL-3.0) fait déjà de l'extraction et de la vérification de liens de
dépôts. Son code n'est pas réutilisable ici — langage et licence incompatibles — mais ses **modes
d'échec mesurés sur 1 861 articles** le sont, et valent plus que du code : césure d'URL par GROBID,
section « références » exclue par défaut, motif Figshare non couvert. Les trois sont des tests de
régression nommés dans `tests/test_normalize.py`. Détail et sources : `docs/etat-de-lart.md` §2.2.

L'apport propre de ce dépôt : les sondes d'existence par API avec raison de classification nommée,
la séparation `restricted` / `unknown`, la distinction « mort » / « n'a jamais existé » via Software
Heritage, et le jeu de contrôle à vérité fabriquée.

## Règle d'arrêt

Si l'hypothèse H1 est réfutée — les liens survivent bien —, on publie le résultat positif, qui est
une information publiable en soi, et on s'arrête. Pas d'entretien par inertie.

Le plan complet : [`PLAN.md`](PLAN.md).
