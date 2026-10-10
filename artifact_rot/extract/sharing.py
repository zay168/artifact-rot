"""Detecting data- and code-sharing statements.

**Method taken from ODDPub** (Riedel, Kip & Bobrov, *ODDPub — a Text-Mining Algorithm to
Detect Data Sharing in Biomedical Publications*, Data Science Journal, 2020,
https://doi.org/10.5334/dsj-2020-042). The paper is under **CC BY 4.0**, so the method
and its category structure can be reused with attribution.

The ODDPub package itself is in **R and under AGPL-3.0**: its code cannot be reused in a
Python stack without contaminating the licence. As with `metacheck`, we reuse the
**published method**, not the code — and we say so.

What is reused: the idea that a sharing statement is detected by **co-occurrence of
keyword categories** within the same sentence, and the split into categories (specialised
repository + accession number, general-purpose repository, supplementary material, source
code). What is specific to this repository: the lists themselves, rewritten to cover four
disciplines and not only biomedicine, and the link with the four states of §4.

Performance reported by the authors on their biomedical corpus, as a reference point and
not a promise about ours: sensitivity 0.73 / specificity 0.97 for open data; sensitivity
0.94 / specificity 0.82 for open code.

**What this module does not do**: it does not say whether a link resolves. It says whether
the paper *announces* sharing. Crossing the two is the project's real result — "X% of
papers announce sharing; among them, Y% have a link that still resolves" is a much
stronger sentence than a dead-link rate alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Category 1: specialised repositories, recognisable by their accession number ----
# The co-occurrence "repository name" + "accession number" is the most reliable signal
# there is: an accession number is not written by chance.

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
"""Identifier patterns **specific to a named repository**, nothing else.

Two generic patterns were removed after measurement on 2026-09-20: `[A-Z]{1,2}\\d{5,}`
and `\\d[A-Z0-9]{3}` (the shape of a PDB code). They fired on bibliographic reference
numbers and made a citation list look like a sharing statement. A pattern this short only
makes sense next to the name of its repository, never alone — and the co-occurrence
required here was not enough to catch it."""

ACCESSION_WORDS = re.compile(
    r"""(?ix)\b(accession\s+(?:number|code|no\.?|id)s?
      | under\s+accession | deposited\s+(?:in|at|under)
      | study\s+identifier)\b"""
)

# --- Category 2: general-purpose repositories ---------------------------------------

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

# --- Category 3: supplementary material ----------------------------------------------

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

# --- Category 4: source code ----------------------------------------------------------

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

# --- Counter-indications --------------------------------------------------------------

RESTRICTED_WORDS = re.compile(
    r"""(?ix)\b(
        (?:the\s+)?data\s+(?:are|is|were|was)\s+not\s+(?:publicly\s+)?(?:available|shared)
      | (?:cannot|can\s?not)\s+be\s+(?:publicly\s+)?(?:shared|released|made\s+available)
      | restricted\s+access | data\s+use\s+agreement
      | ethical\s+restrictions? | patient\s+privacy
      | material\s+transfer\s+agreement
    )\b"""
)
"""A paper may state explicitly that it does **not** share, often for legitimate reasons
(patient data). Counting it as sharing would be wrong, and counting it as a dead link
would be worse.

Tightened on 2026-09-20: the broad form `(not|no)\\s+...\\s+available` fired on "these
symmetries are not generally available in curved space time", a theoretical-physics
sentence with no connection at all. The subject must now be the data."""

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


@dataclass
class SharingSignals:
    """What the paper **announces**. Never what resolves."""

    open_data: bool = False
    open_code: bool = False
    supplement_only: bool = False
    explicitly_restricted: bool = False
    on_request: bool = False
    categories: list[str] = field(default_factory=list)
    sentences: list[str] = field(default_factory=list)
    """The sentences that triggered detection. Without them, a disagreement over a
    published figure cannot be arbitrated — same requirement as for probe evidence."""

    @property
    def claims_sharing(self) -> bool:
        return self.open_data or self.open_code or self.supplement_only


def detect(text: str, *, max_sentences: int = 12) -> SharingSignals:
    """Detect sharing announcements by co-occurrence of categories within a sentence.

    ODDPub's principle: a single category is not enough. "github" in a bibliography
    announces nothing; "the analysis code is available at github.com/…" does. It is
    co-occurrence within **the same sentence** that carries the signal.
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
