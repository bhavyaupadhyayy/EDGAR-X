"""ExtractionAgent: structured qualitative claims from real 10-K text.

Input is the MD&A and risk-factors text of one filing (RAW_FILINGS). Output
is a list of claims, each tagged with the filing section it came from and a
short verbatim quote as evidence. The code — not the model — supplies the
provenance envelope (accession number, table reference), so attribution can
never be hallucinated. Missing sections are declared as data gaps; if no
text exists at all, the agent returns an empty result WITHOUT calling the API.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from agents.base_agent import BaseAgent, cached_text_block
from agents.data_access import FilingText
from core.logging import get_logger

logger = get_logger(__name__)


class FilingClaim(BaseModel):
    """One qualitative claim, attributed to its filing section."""

    claim: str
    category: Literal["business_driver", "stated_risk", "forward_looking"]
    source_section: Literal["mdna", "risk_factors"]
    source_quote: str


class ExtractionClaims(BaseModel):
    """What the model returns: claims plus declared gaps."""

    claims: list[FilingClaim]
    data_gaps: list[str]


class ExtractionResult(BaseModel):
    """Code-supplied provenance envelope around the model output."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    fiscal_year: int
    accession_number: str
    sources: list[str]
    claims: list[FilingClaim]
    data_gaps: list[str]


_SYSTEM_PROMPT = """\
You are the extraction agent of EDGAR-X, a financial research system. You \
receive the MD&A and risk-factors sections of one real SEC 10-K filing, each \
introduced by a [SECTION: ...] marker.

Extract the key qualitative claims a research analyst would care about:
- business_driver: what management says drove or will drive results
- stated_risk: risks the company explicitly discloses
- forward_looking: explicit forward-looking statements or guidance

Hard rules:
1. Every claim MUST come from the provided text. Never use outside knowledge.
2. source_section MUST be the section the claim came from.
3. source_quote MUST be a short verbatim excerpt (under 200 characters) copied \
from that section that supports the claim. Do not paraphrase inside the quote.
4. If a section is marked [SECTION ... : MISSING], do not invent content for \
it — note the limitation in data_gaps instead.
5. Report the 6-9 MOST material claims only. Be terse: every source_quote \
under 150 characters, every claim one sentence. Your entire JSON response \
must fit comfortably within 3,000 tokens — truncated output is discarded \
and wastes the call.
"""


class ExtractionAgent(BaseAgent[ExtractionClaims]):
    """Extracts attributed qualitative claims from one filing's text."""

    agent_name: ClassVar[str] = "extraction"
    max_output_tokens: ClassVar[int] = 4000
    output_schema: ClassVar[type[BaseModel]] = ExtractionClaims
    system_prompt: ClassVar[str] = _SYSTEM_PROMPT

    def run(self, filing: FilingText) -> ExtractionResult:
        """Extract claims from one filing.

        Args:
            filing: The real filing text (from RAW_FILINGS).

        Returns:
            Attributed claims wrapped in a code-supplied provenance envelope.
            If the filing has no usable text at all, an empty result with an
            explicit data gap — no API call is made.
        """
        gaps: list[str] = []
        if not filing.mdna_text:
            gaps.append(f"mdna_text missing for {filing.accession_number}")
        if not filing.risk_factors_text:
            gaps.append(f"risk_factors_text missing for {filing.accession_number}")
        if not filing.mdna_text and not filing.risk_factors_text:
            logger.warning("extraction_no_text", accession=filing.accession_number)
            return ExtractionResult(
                ticker=filing.ticker,
                fiscal_year=filing.fiscal_year,
                accession_number=filing.accession_number,
                sources=[filing.source_reference],
                claims=[],
                data_gaps=gaps + ["no extraction performed: filing has no section text"],
            )

        output = self.run_prompt(
            ticker=filing.ticker,
            user_content=[
                cached_text_block(_render_filing(filing)),
                {
                    "type": "text",
                    "text": (
                        f"Extract the key claims from this {filing.ticker} 10-K "
                        f"covering fiscal year {filing.fiscal_year}."
                    ),
                },
            ],
        )
        return ExtractionResult(
            ticker=filing.ticker,
            fiscal_year=filing.fiscal_year,
            accession_number=filing.accession_number,
            sources=[filing.source_reference],
            claims=output.claims,
            data_gaps=gaps + output.data_gaps,
        )


def _render_filing(filing: FilingText) -> str:
    """Render the filing sections with explicit markers for attribution."""
    mdna = filing.mdna_text or "MISSING"
    risk = filing.risk_factors_text or "MISSING"
    return (
        f"[SECTION mdna ({filing.accession_number})"
        f"{' : MISSING' if not filing.mdna_text else ''}]\n{mdna}\n\n"
        f"[SECTION risk_factors ({filing.accession_number})"
        f"{' : MISSING' if not filing.risk_factors_text else ''}]\n{risk}"
    )
