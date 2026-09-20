# E3 — Trouver les liens dans les articles

> Critère de passage (PLAN.md §7) : **rappel vérifié sur un sous-ensemble où les liens sont
> déjà connus via métadonnées structurées.**
> **Vérifié au 2026-09-20. Le résultat est mauvais, et c'est l'information utile.**

---

## 1. La vérité terrain se fabrique, encore une fois

Il n'a pas fallu annoter un seul article. Tout document publié porte ses liens **balisés par
l'éditeur** :

- un PDF les stocke en annotations `/URI` — c'est ce qui rend un lien cliquable ;
- un JATS les balise en `<ext-link>` ;
- une page HTML les met en `<a href>`.

Notre extracteur, lui, travaille sur le **texte rendu**. Le rappel se mesure de l'un contre
l'autre. Même principe que celui qui fonde le projet entier : quand la vérité terrain coûte cher,
on déplace l'expérience là où elle se fabrique seule.

## 2. Le chiffre

Sur 187 documents PDF et JATS du sous-échantillon :

| | liens balisés | retrouvés dans le texte | rappel |
|---|---|---|---|
| **Ensemble** | 1 359 | 673 | **0,495** |
| DOI (bibliographie surtout) | 1 347 | 669 | 0,497 |
| Dépôts (GitHub, Zenodo, OSF…) | 12 | 4 | 0,333 |

Et dans l'autre sens : **690 liens trouvés dans le texte que le balisage ne contient pas.**

**Conclusion, qui est la vraie sortie d'E3 : ni l'une ni l'autre des deux sources ne suffit.**
L'extraction textuelle rate la moitié de ce que l'éditeur a balisé ; le balisage rate 690 liens
que le texte porte en clair. L'extracteur de production prend donc **l'union des deux**, ce qui
était déjà le cas dans `extract/links.py`, et ce qui est désormais justifié par une mesure au lieu
d'une intuition.

### La réserve à ne pas cacher

**Douze liens de dépôt, c'est trop peu pour conclure quoi que ce soit** sur le rappel de la
population qui intéresse réellement le projet. 0,333 sur n = 12, c'est quatre liens sur douze.
Ce chiffre ne doit pas être cité.

C'est en soi un résultat : sur 400 articles en accès ouvert, le balisage éditorial ne déclare que
douze liens de dépôt. Les liens d'artefacts sont **rares**, et le sous-échantillon d'E3 devra être
nettement agrandi avant E5 pour que le rappel par famille veuille dire quelque chose.

## 3. Trois défauts trouvés en mesurant, pas en relisant

### 3.1 Une page de notice n'est pas un article — le plus grave

La première version classait les localisations par type de source : dépôts d'abord, éditeurs
ensuite. Elle choisissait donc la **page de notice** d'un dépôt (`zenodo.org/records/…`) avant le
PDF de l'éditeur.

Or une page de notice n'est pas l'article. Son texte est celui du site hôte, et ses liens sont ceux
de son menu et de son pied de page.

Le défaut n'était pas visible à la récupération : elle « marchait », elle rendait 200 et du HTML.
Il est apparu au calcul du rappel, sous une forme déroutante : les liens de dépôt soi-disant
manqués étaient les liens du site Zenodo **vers son propre code** — `github.com/zenodo/zenodo-rdm`,
`zenodo.org/help/statistics`. Sur 78 liens de dépôt manqués, 70 étaient de ce type.

Sans cette mesure, le run S1 complet aurait extrait les liens de pages de notice au lieu
d'articles, et produit un taux de survie parfaitement propre et parfaitement faux.

Correction : **tout PDF passe avant toute page HTML.** L'ordre est désormais PDF de dépôt, PDF
d'éditeur, page de dépôt, page d'éditeur.

> **Conséquence opérationnelle** : le cache de textes intégraux constitué avant cette correction
> contient des pages de notice. Il doit être **reconstruit avant E5**.

### 3.2 Le rappel mesuré sur du HTML ne veut rien dire

Corollaire du précédent. Une page HTML mélange l'article et l'habillage du site, et aucune règle
par expression régulière ne les sépare de façon fiable. Les annotations d'un PDF et les
`<ext-link>` d'un JATS, elles, appartiennent au document.

Le rappel n'est donc calculé que sur PDF et JATS. **125 pages HTML ont été écartées du calcul**, et
ce nombre est reporté à chaque exécution plutôt que tu.

### 3.3 Une URL réelle faisait tomber le pipeline

Le calcul s'est arrêté net sur `ValueError: Invalid IPv6 URL` — un `[` isolé dans une URL trouvée
dans un PDF suffit à faire lever `urlsplit` de la bibliothèque standard.

Une URL d'article est une chaîne trouvée dans un PDF : elle peut être n'importe quoi. Aucune
fonction de `normalize.py` ne doit lever à cause d'elle. Sept URL hostiles sont entrées comme
régressions.

Sur un run de 40 000 articles, ce défaut aurait interrompu le traitement à un moment imprévisible.

## 4. Les causes des liens manqués, comptées

Sur les liens de dépôt balisés et non retrouvés dans le texte :

| cause | part | corrigeable ? |
|---|---|---|
| absente du texte (lien posé derrière un mot cliquable) | 73 % | non — limite du monde, pas du code |
| hôte cité mais URL masquée | 12 % | non |
| césure PDF non réparée | 10 % | partiellement |
| présente mais ratée par l'extraction | 5 % | oui |

Les 85 % du haut du tableau ne sont **pas** un défaut de l'extracteur : quand un éditeur écrit
« our GitHub repository » et met l'URL derrière le mot, aucune lecture du texte ne peut la
retrouver. C'est précisément pourquoi le balisage entre dans l'union.

La césure PDF reste partiellement irréductible : une URL coupée au milieu d'un segment de chemin
(`low-code-LLM-CDE-` puis retour à la ligne puis `extraction`) ne peut pas être recollée sans
risquer d'inventer des liens. Recoller large serait pire que manquer.

## 5. Récupération du texte intégral : ce qui est accessible

Trois mesures faites avant d'écrire la moindre ligne :

- **PDF 54 %, HTML 7 %** parmi les localisations de `best_oa_location`. Un extracteur HTML seul
  aurait mesuré une discipline, pas quatre.
- **Europe PMC ne couvre que la médecine** : 38 % des articles médicaux en JATS, 1 à 2 % ailleurs.
  Excellente source, pas une source d'échantillon.
- **Préférer les dépôts fait passer la récupération de 61 % à 72 %**, et le moissonnage réel
  atteint ~80 %. Wiley, ScienceDirect, MDPI et OUP répondent 403 à un robot ; arXiv, PMC et les
  dépôts institutionnels non.

On va chercher ailleurs une copie que l'auteur a lui-même déposée. **Aucun 403 n'est forcé**, aucun
blocage n'est contourné (§4, piège 5).

**L'attrition résiduelle (~20 %) est une limite à publier**, et à ventiler par strate : si elle est
corrélée à l'année, elle biaise la variable explicative principale du projet.

## 6. Provenance d'un lien

Un lien annoncé dans « Data Availability » est une promesse explicite de l'article. Le même lien
dans la bibliographie peut appartenir à un article cité. Les confondre reviendrait à attribuer à
des auteurs une promesse qu'ils n'ont pas faite — ce que le §9 interdit.

Trois provenances : `availability_statement`, `body`, `references`. La bibliographie est repérée à
la **dernière** occurrence du titre, pas la première : un article mentionne souvent « References »
dans un sommaire avant la vraie section, et prendre la première classerait la moitié du corps de
texte en provenance douteuse.

Un lien venu des seules annotations est marqué `body` : une annotation ne dit pas dans quelle
section elle se trouve.

## 7. Commandes

```bash
export ARTIFACT_ROT_CONTACT="vous@exemple.org"

uv run python -m artifact_rot.harvest fetch 400    # telecharge et met en cache
uv run python -m artifact_rot.harvest recall       # mesure le rappel
uv run python -m artifact_rot.harvest links        # produit les liens a sonder
```
