"""Reperage des sections de disponibilite, et de la bibliographie.

Deux usages, tous deux exiges par le §4 :

* **Localiser les declarations de disponibilite** pour savoir d'ou vient un lien. Un
  lien annonce dans « Data Availability » est une promesse explicite ; le meme lien dans
  une note de bas de page n'en est pas une. Les deux sont extraits, la provenance les
  separe.
* **Localiser la bibliographie**, parce que metacheck a mesure que 3 % des articles de
  son corpus ne citent un depot que la (issue #411). Les exclure perd ces cas ; les
  inclure sans les marquer attribue a un article le depot d'un article qu'il cite. On
  extrait, on marque, et le rapport tranche.

Volontairement heuristique et deterministe : pas de modele, pas d'apprentissage, aucun
seuil ajuste apres coup. Une regle qu'on ne peut pas ecrire en une phrase n'a pas sa
place dans un projet dont le livrable est la rigueur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AVAILABILITY_HEADINGS = re.compile(
    r"""(?mix)
    ^[\s\d.]{0,8}
    (
        (?:data|code|software|materials?|resources?)
        (?:\s*(?:,|and|/|&)\s*(?:code|data|software|materials?|resources?))*
        \s+(?:and\s+)?availability(?:\s+statement)?
      | availability\s+of\s+(?:data|code|materials?|supporting\s+data)
      | data\s+access(?:ibility)?(?:\s+statement)?
      | accession\s+(?:codes?|numbers?)
      | code\s+availability
      | open\s+practices?\s+statement
      | data\s+sharing\s+statement
      | disponibilit[ée]\s+des\s+donn[ée]es
      | d[ée]claration\s+de\s+disponibilit[ée]
    )
    \s*[:.\-—]?\s*$
    """
)

INLINE_AVAILABILITY = re.compile(
    r"""(?ix)
    (?:data|code|software|materials?)\s+availability(?:\s+statement)?\s*[:.\-—]
    """
)

REFERENCE_HEADINGS = re.compile(
    r"""(?mix)
    ^[\s\d.]{0,8}
    (references?|bibliography|works\s+cited|literature\s+cited|bibliographie|r[ée]f[ée]rences?)
    \s*[:.\-—]?\s*$
    """
)

NEXT_HEADING = re.compile(
    r"""(?mix)
    ^[\s\d.]{0,8}
    (
        acknowledg(?:e?ments?|ements)
      | references? | bibliography
      | funding | competing\s+interests? | conflicts?\s+of\s+interest
      | author\s+contributions? | ethics(?:\s+statement)?
      | supplementary\s+(?:material|information)
      | appendix | abbreviations
    )
    \s*[:.\-—]?\s*$
    """
)

MAX_STATEMENT_CHARS = 3000
"""Une declaration de disponibilite plus longue que ca n'en est pas une : on est tombe
sur une section mal delimitee, et etendre la fenetre ferait entrer des liens qui ne
sont pas des promesses."""


@dataclass(frozen=True)
class Span:
    label: str
    start: int
    end: int

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


def find_availability_spans(text: str) -> list[Span]:
    """Toutes les declarations de disponibilite, bornees a la section suivante."""
    spans: list[Span] = []

    for m in AVAILABILITY_HEADINGS.finditer(text):
        start = m.end()
        spans.append(Span("availability", start, _section_end(text, start)))

    for m in INLINE_AVAILABILITY.finditer(text):
        # Forme en ligne, frequente dans les PDF ou le titre de section n'est pas isole
        # sur sa ligne. Bornee au paragraphe.
        start = m.end()
        para = text.find("\n\n", start)
        end = para if para != -1 else start + MAX_STATEMENT_CHARS
        spans.append(Span("availability", start, min(end, start + MAX_STATEMENT_CHARS)))

    return _merge(spans)


def _section_end(text: str, start: int) -> int:
    nxt = NEXT_HEADING.search(text, start)
    end = nxt.start() if nxt else len(text)
    return min(end, start + MAX_STATEMENT_CHARS)


def find_references_span(text: str) -> Span | None:
    """La bibliographie : **la derniere** occurrence du titre, pas la premiere.

    Un article mentionne souvent « References » dans son sommaire ou dans une legende
    avant la vraie section. Prendre la premiere occurrence classerait la moitie du corps
    de texte en bibliographie, et donc en provenance douteuse.
    """
    matches = list(REFERENCE_HEADINGS.finditer(text))
    if not matches:
        return None
    last = matches[-1]
    return Span("references", last.end(), len(text))


def _merge(spans: list[Span]) -> list[Span]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: s.start)
    out = [ordered[0]]
    for span in ordered[1:]:
        if span.start <= out[-1].end:
            out[-1] = Span(out[-1].label, out[-1].start, max(out[-1].end, span.end))
        else:
            out.append(span)
    return out


def classify_position(pos: int, availability: list[Span], references: Span | None) -> str:
    """D'ou vient un lien trouve a la position `pos` ? Voir `models.LinkSource`."""
    for span in availability:
        if span.start <= pos < span.end:
            return "availability_statement"
    if references and pos >= references.start:
        return "references"
    return "body"
