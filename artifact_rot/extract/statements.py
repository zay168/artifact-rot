"""Locating availability sections, and the bibliography.

Two uses, both required by §4:

* **Locate availability statements** to know where a link comes from. A link announced in
  "Data Availability" is an explicit promise; the same link in a footnote is not. Both are
  extracted; provenance separates them.
* **Locate the bibliography**, because metacheck measured that 3% of the papers in its
  corpus cite a repository only there (issue #411). Excluding them loses these cases;
  including them unmarked attributes to a paper the repository of a paper it cites. We
  extract, we mark, and the report decides.

Deliberately heuristic and deterministic: no model, no learning, no threshold tuned after
the fact. A rule that cannot be written in one sentence has no place in a project whose
deliverable is rigour.
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
    (?:data|code|software|materials?)\s+availability(?:\s+statement)?
    (?:
        \s*[:.\-—]          # explicit punctuation after the heading
      # Or nothing at all: the heading runs straight into the sentence. The capital
      # letter that follows is what distinguishes a heading from an ordinary mention,
      # hence the `(?-i:...)` that locally disables case insensitivity — without it,
      # `re.IGNORECASE` makes `[A-Z]` equivalent to `[A-Za-z]` and "we discuss data
      # availability in section 4" passes for a section heading.
      | \s+(?=(?-i:[A-Z]))
    )
    """
)
"""Inline form of the heading.

The "no punctuation" variant was added on 2026-09-20 after measurement: of ten documents
containing the phrase, four wrote it without a separator, as in "Data Availability As
declared in the paper that research data will be provided upon receiving requests". PDF
extraction glues the heading to the paragraph, and requiring a colon lost 40% of cases."""

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
"""An availability statement longer than this is not one: we have hit a badly delimited
section, and widening the window would bring in links that are not promises."""


@dataclass(frozen=True)
class Span:
    label: str
    start: int
    end: int

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


def find_availability_spans(text: str) -> list[Span]:
    """Every availability statement, bounded by the next section."""
    spans: list[Span] = []

    for m in AVAILABILITY_HEADINGS.finditer(text):
        start = m.end()
        spans.append(Span("availability", start, _section_end(text, start)))

    for m in INLINE_AVAILABILITY.finditer(text):
        # Inline form, common in PDFs where the section heading is not alone on its line.
        # Bounded by the paragraph.
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
    """The bibliography: **the last** occurrence of the heading, not the first.

    A paper often mentions "References" in its table of contents or in a caption before
    the real section. Taking the first occurrence would class half the body text as
    bibliography, and thus as doubtful provenance.
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
    """Where does a link found at position `pos` come from? See `models.LinkSource`."""
    for span in availability:
        if span.start <= pos < span.end:
            return "availability_statement"
    if references and pos >= references.start:
        return "references"
    return "body"
