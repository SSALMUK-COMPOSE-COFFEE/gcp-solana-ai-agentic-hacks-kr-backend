import json
from typing import Literal

import httpx
from fastapi import HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings

NOT_CONFIGURED = "AI 에이전트가 설정되지 않았습니다."
EVALUATION_FAILED = "정책 판단에 실패했습니다. 잠시 후 다시 시도해 주세요."

USDC_UNIT = 1_000_000
FILE_MAX_BYTES = 15 * 1024 * 1024
READABLE_TYPES = ("image/", "application/pdf")

SYSTEM_INSTRUCTION = """너는 팬덤 모금 캠페인의 지출을 심사하는 정책 판단 에이전트다.
총대(운영자)가 자금을 임의로 쓰지 못하도록, 벤더의 지출 요청이 캠페인 정책에 맞는지만 판단한다.

금액 단위가 두 가지다. 혼동하면 판단 전체가 틀린다.
- JSON 자료의 금액은 USDC raw units다. 1 USDC = 1,000,000 raw units.
- 첨부된 증빙 파일의 금액은 사람이 읽는 USDC 표기다. 파일의 "5,000"은 raw units로 5,000,000,000이다.
- 비교할 때는 반드시 같은 단위로 환산한 뒤 비교한다.
- JSON에는 각 금액마다 raw 값과 USDC 표기를 함께 제공하므로, 파일과 대조할 때는 USDC 표기를 쓴다.
- required_amount는 raw units로 출력한다.

다음을 순서대로 확인한다.
1. 벤더가 allowlist에 등재되어 있는가. 미등재면 다른 조건과 무관하게 거절한다.
2. 벤더와 증빙의 카테고리가 캠페인 카테고리와 맞는가.
3. 단가와 총액이 캠페인 정책의 한도 안에 있는가.
4. 증빙 파일이 주어졌다면, 파일에 적힌 항목·단가·총액이 신고된 값과 일치하는가.
   단위를 환산해 비교하고, 값이 같으면 일치한다고 판단한다.
   불일치할 때만 거절하고, 어떤 값이 얼마에서 얼마로 다른지 숫자를 적는다.
5. 에스크로 잔액으로 이 지출을 감당할 수 있는가.
   부족하면 (신고_총액 - 에스크로_잔액)을 raw units로 required_amount에 넣는다. 충분하면 0을 넣는다.

reasons는 한국어로, 판단 근거를 항목당 한 문장씩 쓴다. 확인한 숫자를 근거에 포함한다.
추측하지 말고 주어진 자료에 있는 사실만 근거로 삼는다.
자료가 부족해 확인할 수 없는 항목이 있으면 그 사실을 reasons에 적고 거절한다.
서로 모순되는 근거를 쓰지 않는다."""


class PolicyDecision(BaseModel):
    decision: Literal["approve", "reject"]
    required_amount: int
    reasons: list[str]


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return genai.Client(api_key=settings.gemini_api_key)


async def fetch_document(url: str | None) -> types.Part | None:
    if not url or not url.startswith(("http://", "https://")):
        return None

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return None

    if response.status_code >= 400 or len(response.content) > FILE_MAX_BYTES:
        return None

    mime_type = response.headers.get("content-type", "").split(";")[0].strip()
    if not mime_type.startswith(READABLE_TYPES):
        return None

    return types.Part.from_bytes(data=response.content, mime_type=mime_type)


def amount(raw: int) -> dict:
    return {"raw": raw, "usdc": f"{raw / USDC_UNIT:,.2f}"}


def build_prompt(campaign: dict, vendor: dict, proof: dict, escrow_balance: int) -> str:
    payload = {
        "캠페인": campaign,
        "에스크로_잔액": amount(escrow_balance),
        "벤더": vendor,
        "지출_증빙": proof,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def evaluate_policy(prompt: str, document: types.Part | None) -> PolicyDecision:
    parts: list = [types.Part.from_text(text=prompt)]
    if document is not None:
        parts.append(document)

    try:
        response = await _client().aio.models.generate_content(
            model=settings.gemini_model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=PolicyDecision,
                temperature=0.0,
            ),
        )
    except Exception:
        raise HTTPException(status_code=502, detail=EVALUATION_FAILED) from None

    decision = response.parsed
    if not isinstance(decision, PolicyDecision):
        raise HTTPException(status_code=502, detail=EVALUATION_FAILED)

    return decision
