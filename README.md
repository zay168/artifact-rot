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
| E1 — échantillonnage stratifié figé | à faire |
| E2 — sondes et classification | **passé** au 2026-09-20 : 119/120, soit 0,9917 pour un seuil à 0,98. Réserve écrite : `restricted` est à 0,667 sur n = 3 ([`docs/jeu-de-controle.md`](docs/jeu-de-controle.md)) |
| E3 — extraction depuis le texte intégral | à faire |
| E4 — ordonnanceur 3 passes | à faire |
| E5 — run officiel S1 | à faire |
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

uv run pytest                                    # 72 tests hors ligne

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
