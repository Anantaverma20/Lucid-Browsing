"""
POST /verify: News Truth – extract claims (Bem or Gemini), Fact Hunter search, Truth Judge, aggregate score.
"""
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import config
from backend.agents.truth.fact_hunter import search_claim
from backend.agents.truth.judge import judge_claim
from backend.services.bem_client import extract_claims, flatten_and_filter_claims

logger = logging.getLogger(__name__)

router = APIRouter(tags=["verify"])


class VerifyRequest(BaseModel):
    url: str = Field("", description="Page URL for context or for Bem to fetch")
    content: str = Field("", description="Fallback page text when URL is not usable or for extraction")
    image_base64: str | None = Field(None, description="Optional screenshot for image-based fact-check")


class ClaimResult(BaseModel):
    claim: str
    verdict: Literal["True", "False", "Unverified"]
    confidence: int
    explanation: str
    source_url: str | None


class VerifyResponse(BaseModel):
    page_trust_score: float = Field(..., description="0-100 aggregate trust score")
    claims: list[ClaimResult] = Field(default_factory=list)


def _compute_page_trust_score(claims: list[dict]) -> float:
    """Average confidence weighted by verdict: True contributes positively, False negatively, Unverified neutral."""
    if not claims:
        return 50.0
    total = 0.0
    for c in claims:
        conf = max(0, min(100, c.get("confidence", 0)))
        v = c.get("verdict", "Unverified")
        if v == "True":
            total += conf
        elif v == "False":
            total += 100 - conf  # invert: high confidence in False -> low trust
        else:
            total += 50  # Unverified counts as midpoint
    return round(total / len(claims), 1)


@router.post("/verify", response_model=VerifyResponse)
async def verify(request: VerifyRequest) -> VerifyResponse:
    """
    Fact-check the current page or screenshot: extract claims, search trusted sources, judge each claim.
    Returns page_trust_score (0-100) and per-claim verdicts with explanations and source links.
    """
    try:
        config.ensure_truth_config()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    url = (request.url or "").strip()
    content = (request.content or "").strip()
    image_base64 = (request.image_base64 or "").strip() or None

    if not url and not content and not image_base64:
        raise HTTPException(status_code=400, detail="Provide at least one of: url, content, or image_base64.")

    # 1) Extract claims (Bem or Gemini from URL / content / image)
    try:
        items = extract_claims(
            url=url or None,
            content=content or None,
            image_base64=image_base64,
        )
    except Exception as e:
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    claim_strings = flatten_and_filter_claims(items)
    if not claim_strings:
        return VerifyResponse(
            page_trust_score=50.0,
            claims=[],
        )

    # 2) For each claim: Fact Hunter -> Truth Judge
    results: list[ClaimResult] = []
    for claim in claim_strings[:15]:
        try:
            evidence = search_claim(claim, timeout=10.0)
            judge_out = judge_claim(claim, evidence, timeout=12.0)
            results.append(
                ClaimResult(
                    claim=claim,
                    verdict=judge_out["verdict"],
                    confidence=judge_out["confidence"],
                    explanation=judge_out["explanation"],
                    source_url=judge_out.get("source_url"),
                )
            )
        except Exception as e:
            logger.warning("Claim evaluation failed for %s: %s", claim[:50], e)
            results.append(
                ClaimResult(
                    claim=claim,
                    verdict="Unverified",
                    confidence=0,
                    explanation=f"Search or judge failed: {str(e)[:150]}",
                    source_url=None,
                )
            )

    # 3) Aggregate score and return
    score = _compute_page_trust_score([r.model_dump() for r in results])
    return VerifyResponse(page_trust_score=score, claims=results)
