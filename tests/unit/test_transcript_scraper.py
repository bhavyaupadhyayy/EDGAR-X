"""Unit tests for the earnings-call transcript scraper (HTTP mocked)."""

from __future__ import annotations

import pytest
import respx

from ingestion.sources.transcript_scraper import TranscriptParseError, TranscriptScraper

URL = "https://www.fool.com/earnings/call-transcripts/2026/05/01/apple-aapl-q2-2026.aspx"

TRANSCRIPT_HTML = """
<html>
  <body>
    <h1>Apple (AAPL) Q2 2026 Earnings Call Transcript</h1>
    <article>
      <h2>Prepared Remarks</h2>
      <p><strong>Operator</strong></p>
      <p>Good afternoon and welcome to the Apple Q2 earnings call.</p>
      <p><strong>Tim Cook</strong> -- <em>Chief Executive Officer</em></p>
      <p>Thank you. We set a March quarter revenue record.</p>
      <p>Services grew double digits year over year.</p>
      <h2>Questions &amp; Answers</h2>
      <p><strong>Analyst One</strong> -- <em>Big Bank</em></p>
      <p>Can you talk about gross margin trajectory?</p>
      <p><strong>Luca Maestri</strong> -- <em>Chief Financial Officer</em></p>
      <p>We expect margins to remain in the guided range.</p>
    </article>
  </body>
</html>
"""


class TestParseHtml:
    """Pure parsing logic on a canned page."""

    def test_parses_title_metadata(self) -> None:
        transcript = TranscriptScraper.parse_html(TRANSCRIPT_HTML, url=URL)
        assert transcript.company_name == "Apple"
        assert transcript.ticker == "AAPL"
        assert transcript.quarter == 2
        assert transcript.fiscal_year == 2026
        assert transcript.url == URL

    def test_splits_prepared_remarks_and_qa(self) -> None:
        transcript = TranscriptScraper.parse_html(TRANSCRIPT_HTML, url=URL)
        sections = {segment.section for segment in transcript.segments}
        assert sections == {"prepared_remarks", "qa"}
        qa_speakers = [s.speaker for s in transcript.segments if s.section == "qa"]
        assert qa_speakers == ["Analyst One", "Luca Maestri"]

    def test_speaker_roles_and_multiparagraph_text(self) -> None:
        transcript = TranscriptScraper.parse_html(TRANSCRIPT_HTML, url=URL)
        cook = next(s for s in transcript.segments if s.speaker == "Tim Cook")
        assert cook.role == "Chief Executive Officer"
        assert "revenue record" in cook.text
        assert "Services grew" in cook.text

    def test_unparseable_page_raises(self) -> None:
        with pytest.raises(TranscriptParseError):
            TranscriptScraper.parse_html("<html><body><p>404</p></body></html>", url=URL)

    def test_unrecognised_title_falls_back(self) -> None:
        html = TRANSCRIPT_HTML.replace(
            "Apple (AAPL) Q2 2026 Earnings Call Transcript", "Some Other Headline"
        )
        transcript = TranscriptScraper.parse_html(html, url=URL)
        assert transcript.ticker is None
        assert transcript.company_name == "Some Other Headline"

    def test_kafka_payload_shape(self) -> None:
        transcript = TranscriptScraper.parse_html(TRANSCRIPT_HTML, url=URL)
        payload = transcript.to_kafka_payload()
        assert payload["ticker"] == "AAPL"
        assert payload["segments"][0]["speaker"] == "Operator"
        assert payload["ingested_at"].tzinfo is not None


class TestFetchTranscript:
    """End-to-end fetch with mocked HTTP."""

    async def test_fetch_and_parse(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get(URL).respond(200, text=TRANSCRIPT_HTML)
        async with TranscriptScraper() as scraper:
            transcript = await scraper.fetch_transcript(URL)
        assert transcript.ticker == "AAPL"
        assert len(transcript.segments) == 4

    async def test_retries_on_transient_error(self, respx_mock: respx.MockRouter) -> None:
        import httpx

        route = respx_mock.get(URL)
        route.side_effect = [httpx.Response(503), httpx.Response(200, text=TRANSCRIPT_HTML)]
        async with TranscriptScraper(backoff_base=0.01) as scraper:
            transcript = await scraper.fetch_transcript(URL)
        assert route.call_count == 2
        assert transcript.company_name == "Apple"
