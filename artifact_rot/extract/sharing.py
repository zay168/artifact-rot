"""Detection des declarations de partage de donnees et de code.

**Methode reprise d'ODDPub** (Riedel, Kip & Bobrov, *ODDPub — a Text-Mining Algorithm to
Detect Data Sharing in Biomedical Publications*, Data Science Journal, 2020,
https://doi.org/10.5334/dsj-2020-042). L'article est sous **CC BY 4.0**, donc la methode
et sa structure de categories se reprennent avec attribution.

Le paquet ODDPub lui-meme est en **R et sous AGPL-3.0** : son code n'est pas reutilisable
dans une pile Python sans contaminer la licence. Comme pour `metacheck`, on reprend la
**methode publiee**, pas le code — et on le dit.

Ce qui est repris : l'idee qu'une declaration de partage se detecte par **co-occurrence
de categories de mots-cles** dans une meme phrase, et le decoupage en categories
(depot specialise + numero d'acces, depot generaliste, materiel supplementaire, code
source). Ce qui est propre a ce depot : les listes elles-memes, reecrites pour couvrir
quatre disciplines et pas seulement la biomedecine, et l'articulation avec les quatre
etats du §4.

Performances rapportees par les auteurs sur leur corpus biomedical, a titre de repere et
non de promesse sur le notre : sensibilite 0,73 / specificite 0,97 pour les donnees
ouvertes ; sensibilite 0,94 / specificite 0,82 pour le code ouvert.

**Ce que ce module ne fait pas** : il ne dit pas si un lien resout. Il dit si l'article
*annonce* un partage. Le croisement des deux est le vrai resultat du projet — « X % des
articles annoncent partager ; parmi eux, Y % ont un lien qui resout encore » est une
phrase bien plus forte qu'un taux de liens morts seul.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Categorie 1 : depots specialises, reconnaissables a leur numero d'acces --------
# La co-occurrence « nom du depot » + « numero d'acces » est le signal le plus sur qui
# existe : un numero d'acces ne s'ecrit pas par hasard.

FIELD_REPOS = re.compile(
    r"""(?ix)\b(
        gene\s+expression\s+omnibus | \bGEO\b
      | sequence\s+read\s+archive | \bSRA\b
      | protein\s+data\s+bank | \bPDB\b
      | european\s+nucleotide\s+archive | \bENA\b
      | arrayexpress | biostudies | biosample | bioproject
      | genbank | dbgap | dbsnp | ensembl | uniprot
      | proteomexchange | \bPRIDE\b | metabolights
      | openneuro | neurovault | \bOpenfMRI\b
      | \bHEPData\b | \bCDS\b | vizier | \bMAST\b | \bIRSA\b
      | \bICPSR\b | \bUK\s+Data\s+Service\b
      | pangaea | \bSEANOE\b
    )\b""",
)

ACCESSION = re.compile(
    r"""(?x)
    \b(
        GSE\d{3,} | SRP\d{5,} | SRR\d{6,} | PRJ[EDN][A-Z]\d{4,}
      | [EDS]R[PRSX]\d{6,} | SAM[END][AG]?\d{6,}
      | PXD\d{6} | MTBLS\d+ | E-[A-Z]{4}-\d+
      | phs\d{6}(?:\.v\d+)? | ds\d{6}
      | CVCL_[A-Z0-9]{4}
    )\b
    """
)
"""Motifs d'identifiants **specifiques a un depot nomme**, rien d'autre.

Deux motifs generiques ont ete retires apres mesure le 2026-09-20 : `[A-Z]{1,2}\\d{5,}`
et `\\d[A-Z0-9]{3}` (la forme d'un code PDB). Ils declenchaient sur des numeros de
reference bibliographique et faisaient passer une liste de citations pour une
declaration de partage. Un motif si court n'a de sens qu'a cote du nom de son depot,
jamais seul — et la co-occurrence exigee ici ne suffisait pas a le rattraper."""

ACCESSION_WORDS = re.compile(
    r"""(?ix)\b(accession\s+(?:number|code|no\.?|id)s?
      | under\s+accession | deposited\s+(?:in|at|under)
      | study\s+identifier)\b"""
)

# --- Categorie 2 : depots generalistes ----------------------------------------------

GENERAL_REPOS = re.compile(
    r"""(?ix)\b(
        zenodo | figshare | dryad | \bOSF\b | open\s+science\s+framework
      | dataverse | mendeley\s+data | harvard\s+dataverse
      | github | gitlab | bitbucket | codeberg | software\s+heritage
      | huggingface | hugging\s+face | kaggle
      | 4TU | \bDANS\b | \bB2SHARE\b | \bRADAR\b
    )\b"""
)

DEPOSIT_VERBS = re.compile(
    r"""(?ix)\b(
        (?:are|is|were|was|have\s+been|has\s+been|can\s+be)\s+
        (?:publicly\s+|freely\s+|openly\s+)?
        (?:available|accessible|found|obtained|downloaded|deposited|archived|hosted)
      | we\s+(?:deposited|archived|uploaded|share|released|made\s+available)
      | available\s+(?:at|from|on|in|via)
      | can\s+be\s+(?:accessed|retrieved|downloaded)
      | disponibles?\s+(?:sur|a|aupres|via)
    )\b"""
)

# --- Categorie 3 : materiel supplementaire -------------------------------------------

SUPPLEMENT = re.compile(
    r"""(?ix)\b(
        supplement(?:ary|al)\s+(?:data|dataset|table|file|material|information)
      | supporting\s+information
      | additional\s+file\s*\d*
      | \bS\d+\s+(?:table|file|data|dataset)\b
    )\b"""
)

DATA_FORMATS = re.compile(
    r"""(?ix)\b(
        \.(?:csv|tsv|xlsx?|sav|dta|rdata|rds|mat|fits|h5|hdf5|nc|netcdf|json|parquet)\b
      | excel\s+(?:file|sheet|spreadsheet)
      | comma[- ]separated
    )"""
)

# --- Categorie 4 : code source --------------------------------------------------------

CODE_WORDS = re.compile(
    r"""(?ix)\b(
        source\s+code | analysis\s+(?:code|scripts?|pipeline)
      | \bR\s+scripts?\b | python\s+scripts? | matlab\s+(?:code|scripts?)
      | code\s+(?:is|are|was|were|will\s+be)\s+available
      | computational\s+(?:code|notebook)
      | jupyter\s+notebook | code\s+repository
      | code\s+source
    )\b"""
)

# --- Contre-indications ---------------------------------------------------------------

RESTRICTED_WORDS = re.compile(
    r"""(?ix)\b(
        (?:the\s+)?data\s+(?:are|is|were|was)\s+not\s+(?:publicly\s+)?(?:available|shared)
      | (?:cannot|can\s?not)\s+be\s+(?:publicly\s+)?(?:shared|released|made\s+available)
      | restricted\s+access | data\s+use\s+agreement
      | ethical\s+restrictions? | patient\s+privacy
      | material\s+transfer\s+agreement
    )\b"""
)
"""Un article peut annoncer explicitement qu'il **ne** partage pas, pour des raisons
souvent legitimes (donnees de patients). Le compter comme un partage serait faux, et le
compter comme un lien mort serait pire.

Resserre le 2026-09-20 : la forme large `(not|no)\\s+...\\s+available` declenchait sur
« these symmetries are not generally available in curved space time », une phrase de
physique theorique sans aucun rapport. Le sujet doit maintenant etre les donnees."""

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass
class SharingSignals:
    """Ce que l'article **annonce**. Jamais ce qui resout."""

    open_data: bool = False
    open_code: bool = False
    supplement_only: bool = False
    explicitly_restricted: bool = False
    on_request: bool = False
    categories: list[str] = field(default_factory=list)
    sentences: list[str] = field(default_factory=list)
    """Les phrases qui ont declenche la detection. Sans elles, un desaccord sur un
    chiffre publie est inarbitrable — meme exigence que pour les preuves de sondes."""

    @property
    def claims_sharing(self) -> bool:
        return self.open_data or self.open_code or self.supplement_only


def detect(text: str, *, max_sentences: int = 12) -> SharingSignals:
    """Detecte les annonces de partage par co-occurrence de categories dans une phrase.

    Le principe d'ODDPub : une seule categorie ne suffit pas. « github » dans une
    bibliographie n'annonce rien ; « the analysis code is available at github.com/… »
    annonce. C'est la co-occurrence dans **la meme phrase** qui porte le signal.
    """
    from .normalize import is_on_request, repair_spaced_hosts

    repaired = repair_spaced_hosts(text)
    signals = SharingSignals()

    for sentence in SENTENCE_SPLIT.split(repaired):
        if not (12 < len(sentence) < 1200):
            continue

        hit: str | None = None

        if FIELD_REPOS.search(sentence) and (
            ACCESSION.search(sentence) or ACCESSION_WORDS.search(sentence)
        ):
            signals.open_data = True
            hit = "field_repo_accession"
        elif GENERAL_REPOS.search(sentence) and DEPOSIT_VERBS.search(sentence):
            if CODE_WORDS.search(sentence):
                signals.open_code = True
                hit = "general_repo_code"
            else:
                signals.open_data = True
                hit = "general_repo_data"
        elif CODE_WORDS.search(sentence) and (
            GENERAL_REPOS.search(sentence) or DEPOSIT_VERBS.search(sentence)
        ):
            signals.open_code = True
            hit = "code_availability"
        elif SUPPLEMENT.search(sentence) and DATA_FORMATS.search(sentence):
            signals.supplement_only = True
            hit = "supplement_data"

        if RESTRICTED_WORDS.search(sentence):
            signals.explicitly_restricted = True
            hit = hit or "explicitly_restricted"

        if is_on_request(sentence):
            signals.on_request = True
            hit = hit or "on_request"

        if hit:
            if hit not in signals.categories:
                signals.categories.append(hit)
            if len(signals.sentences) < max_sentences:
                signals.sentences.append(sentence.strip()[:400])

    return signals
