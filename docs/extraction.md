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

---

## 8. Ce qui existe ailleurs — trois pistes évaluées, une retenue

Le plan impose de regarder avant de construire. Trois outils ou services ont été évalués **sur
notre propre échantillon**, pas sur leur documentation.

### 8.1 ScholExplorer / Scholix — abandonné, et c'est un résultat

[ScholExplorer](https://scholexplorer.openaire.eu/) (OpenAIRE) agrège les liens
publication ↔ jeu de données déclarés par Crossref, DataCite et OpenAIRE. Sur le papier, c'est le
raccourci idéal : on n'extrait plus rien, on interroge une base curée.

Mesure sur 200 articles de notre échantillon ayant un DOI :

| | |
|---|---|
| articles avec au moins un lien Scholix | 126 / 200 (63 %) |
| dont au moins un lien vers un **jeu de données** | **2 / 200 (1 %)** |
| liens `IsRelatedTo → publication` (citations) | 1 060 |
| liens `IsRelatedTo → dataset` | 2 |

**Le graphe curé est quasiment vide pour ce qui nous intéresse.** Ce qu'il contient, ce sont des
citations entre articles. La piste est abandonnée.

C'est en soi une observation à reprendre dans le rapport E6 : non seulement les liens meurent,
mais **les métadonnées structurées censées les enregistrer n'existent quasiment pas**. Un lien de
données annoncé dans un article n'a, dans l'immense majorité des cas, aucune trace ailleurs que
dans le texte de l'article.

### 8.2 GROBID / Docling — pas maintenant, et pour une raison mesurée

[GROBID](https://github.com/grobidOrg/grobid) est la référence pour convertir un PDF scientifique
en XML structuré ; [Docling](https://github.com/docling-project/docling) fait un travail
comparable sans serveur Java. Le projet [pdf4llm](https://github.com/The-Metascience-Observatory/pdf4llm)
montre qu'en combinant les deux on rattrape ~10 % des articles qu'aucun des deux ne traite seul.

Ce serait le réflexe. La mesure dit de s'abstenir pour l'instant :

| indicateur sur nos 187 documents | valeur |
|---|---|
| longueur médiane du texte extrait | 36 767 caractères |
| documents de moins de 5 000 caractères | 6 / 187 |
| césures de fin de ligne | 0,81 pour 1 000 caractères |
| documents au texte visiblement abîmé | 32 / 187 |

**Le texte extrait n'est pas le goulot d'étranglement.** Les articles entiers sortent, et les
liens manqués le sont à 85 % pour des raisons qu'aucun parseur ne corrige — l'URL est posée
derrière un mot cliquable, et seule l'annotation du PDF la contient. Or on lit déjà les
annotations.

Décision : **GROBID reste une option, pas une dépendance.** Elle sera reconsidérée si E5 montre
une attrition corrélée à la qualité du texte. Ajouter un service Java et Docker à un projet mené
seul, pour un gain borné à ~10 % d'un sous-ensemble, est un mauvais échange aujourd'hui.

### 8.3 ODDPub — méthode reprise, code non réutilisable

[ODDPub](https://github.com/quest-bih/oddpub) détecte le partage de données et de code dans les
publications biomédicales. Le paquet est en **R sous AGPL-3.0** : même situation que `metacheck`,
le code n'est pas réutilisable dans une pile Python sans contaminer la licence.

Mais [l'article publié](https://doi.org/10.5334/dsj-2020-042) est sous **CC BY 4.0**, donc la
**méthode** se reprend avec attribution. Ce qui est repris : le principe qu'une annonce de partage
se détecte par **co-occurrence de catégories de mots-clés dans une même phrase**, et le découpage
en catégories. Ce qui est propre à ce dépôt : les listes elles-mêmes, réécrites pour quatre
disciplines au lieu de la seule biomédecine.

Performances rapportées par les auteurs, à titre de repère et non de promesse sur notre corpus :
sensibilité 0,73 / spécificité 0,97 pour les données, 0,94 / 0,82 pour le code.

Résultat de l'implémentation, mesuré sur nos 187 documents : la détection de section est passée de
**7 à 11 documents**, et les faux positifs ont disparu (8 → 0 sur les refus explicites).

Deux faux positifs du corpus réel sont entrés comme régressions nommées :

- « these translational symmetries are **not generally available** in curved space time » —
  déclenchait un refus de partage sur une phrase de physique théorique ;
- une liste de références bibliographiques déclenchait un numéro d'accès, parce que le motif
  générique `[A-Z]{1,2}\d{5,}` attrape des numéros de citation.

Et un bug subtil trouvé au passage : sous `re.IGNORECASE`, `[A-Z]` accepte aussi les minuscules.
La règle « le titre enchaîne sur la phrase, reconnaissable à la majuscule qui suit » ne
fonctionnait donc pas du tout, et « we discuss data availability in section 4 » passait pour un
titre de section.

## 9. La déclaration de disponibilité est une institution récente

Mesure sur nos 187 documents :

| année | articles avec une déclaration de disponibilité |
|---|---|
| 2010 | 0 % |
| 2014 | 2,9 % |
| 2018 | 0 % |
| 2022 | 5,4 % |
| 2025 | **16,3 %** |

Le gradient est net et il est réel — vérifié en cherchant la formule dans le texte brut, pas
seulement via nos règles.

**Conséquence de conception** : restreindre l'extraction aux déclarations de disponibilité ne
produirait quasiment rien sur les strates anciennes, qui sont précisément celles où l'effet d'âge
se mesure. L'extraction porte donc sur **l'article entier**, et la provenance sert à interpréter,
pas à filtrer.

**Conséquence pour E6** : le croisement « l'article annonce-t-il un partage ? » × « le lien
résout-il ? » sera très déséquilibré entre strates. Il devra être publié comme deux mesures
distinctes, jamais comme un taux unique.
