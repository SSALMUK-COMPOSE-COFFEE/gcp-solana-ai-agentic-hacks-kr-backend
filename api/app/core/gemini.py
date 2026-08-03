import base64
import json
from typing import Literal, NamedTuple

from fastapi import HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core import chain, storage
from app.core.config import settings

NOT_CONFIGURED = "AI 에이전트가 설정되지 않았습니다."
EVALUATION_FAILED = "정책 판단에 실패했습니다. 잠시 후 다시 시도해 주세요."

USDC_UNIT = 1_000_000

SYSTEM_INSTRUCTION = """너는 팬덤 모금 캠페인의 지출을 심사하는 정책 판단 에이전트다.
총대(운영자)가 자금을 임의로 쓰지 못하도록, 벤더의 지출 요청이 캠페인 정책에 맞는지만 판단한다.

금액 단위가 두 가지다. 혼동하면 판단 전체가 틀린다.
- JSON 자료의 금액은 USDC raw units다. 1 USDC = 1,000,000 raw units.
- 첨부된 증빙 파일의 금액은 사람이 읽는 USDC 표기다. 파일의 "5,000"은 raw units로 5,000,000,000이다.
- 비교할 때는 반드시 같은 단위로 환산한 뒤 비교한다.
- JSON에는 각 금액마다 raw 값과 USDC 표기를 함께 제공하므로, 파일과 대조할 때는 USDC 표기를 쓴다.
- required_amount는 raw units로 출력한다.

캠페인 정책(policy)의 구조:
- categories: 벤더 카테고리별 한도. maxUnitPrice는 단가 상한, maxTotal은 그 카테고리 지출 총액 상한,
  unitLabel은 단가의 기준 단위(예: "2주 1면"). 모두 raw units다.
- maxPerCategory: 카테고리 구분 없는 공통 총액 상한 (구형 필드).
- allowSurplusScaling: true면 목표를 초과 모금한 비율만큼 한도를 비례 확대해도 된다.
  (예: 목표의 120%를 모금했으면 한도도 120%까지 허용)
- 정책에 해당 카테고리가 없으면 명시된 한도가 없는 것이므로 한도 위반으로 거절하지 않는다.

다음을 순서대로 확인한다.
1. 벤더가 allowlist에 등재되어 있는가. 미등재면 다른 조건과 무관하게 거절한다.
2. 벤더의 카테고리가 캠페인 카테고리와 맞거나, 정책 categories에 명시된 카테고리 중 하나인가.
3. 단가와 총액이 캠페인 정책의 한도 안에 있는가.
4. 증빙 파일이 주어졌다면, 파일에 적힌 항목·단가·총액이 신고된 값과 일치하는가.
   단위를 환산해 비교하고, 값이 같으면 일치한다고 판단한다.
   불일치할 때만 거절하고, 어떤 값이 얼마에서 얼마로 다른지 숫자를 적는다.
4-1. 증빙 파일에 대금 수령 지갑 주소가 적혀 있다면 벤더의 등록 지갑과 같은지 대조한다.
   다르면 거절한다. 파일에 지갑 주소가 없으면 이 항목은 건너뛴다.
4-2. 벤더의 지갑이 총대_지갑과 같으면, 다른 조건과 무관하게 거절한다.
   총대가 벤더를 가장해 모금액을 자기 지갑으로 빼내는 경우이므로 가장 무겁게 다룬다.
5. 에스크로 잔액으로 이 지출을 감당할 수 있는가.
   부족하면 (신고_총액 - 에스크로_잔액)을 raw units로 required_amount에 넣는다. 충분하면 0을 넣는다.
6. 리워드_티어가 판매된 캠페인이면 리워드 이행 예산까지 지킨다.
   - 이 지출이 리워드 구성품 제작이면: 견적 수량이 그 구성품이 포함된 티어들의 판매수 합계 이상인지
     확인한다. 부족하면 거절하고 몇 개가 부족한지 적는다.
   - 이 지출이 리워드 구성품 제작이 아니면: 지출 후 남는 에스크로 잔액이 아직 집행되지 않은 리워드
     제작 예산을 침범하는지 확인한다. 리워드 예산은 정책 categories의 리워드 관련 카테고리 한도
     (maxTotal)를 기준으로 삼고, 기준이 없으면 그 사실만 reasons에 남기고 이 항목으로 거절하지 않는다.
   판매수가 0이면 이 항목은 건너뛴다.

reasons는 한국어로, 판단 근거를 항목당 한 문장씩 쓴다. 확인한 숫자를 근거에 포함한다.
추측하지 말고 주어진 자료에 있는 사실만 근거로 삼는다.
자료가 부족해 확인할 수 없는 항목이 있으면 그 사실을 reasons에 적고 거절한다.
서로 모순되는 근거를 쓰지 않는다."""


class PolicyDecision(BaseModel):
    decision: Literal["approve", "reject"]
    required_amount: int
    reasons: list[str]


class Document(NamedTuple):
    data: bytes
    mime_type: str


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "decision": {"type": "STRING", "enum": ["approve", "reject"]},
        "required_amount": {"type": "INTEGER"},
        "reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["decision", "required_amount", "reasons"],
}


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return genai.Client(api_key=settings.gemini_api_key)


async def fetch_document(url: str | None) -> Document | None:
    path = storage.local_path(url)
    if path is None:
        return None
    return Document(
        data=path.read_bytes(), mime_type=storage.MIME_BY_EXTENSION[path.suffix]
    )


def amount(raw: int) -> dict:
    return {"raw": raw, "usdc": f"{raw / USDC_UNIT:,.2f}"}


def build_prompt(
    campaign: dict,
    vendor: dict,
    proof: dict,
    escrow_balance: int,
    tiers: list[dict] | None = None,
) -> str:
    payload = {
        "캠페인": campaign,
        "에스크로_잔액": amount(escrow_balance),
        "벤더": vendor,
        "지출_증빙": proof,
        "리워드_티어": tiers or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _direct(prompt: str, document: Document | None) -> PolicyDecision:
    parts: list = [types.Part.from_text(text=prompt)]
    if document is not None:
        parts.append(
            types.Part.from_bytes(data=document.data, mime_type=document.mime_type)
        )

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


def _answer_text(response: object) -> str:
    if not isinstance(response, dict):
        raise ValueError("응답 형식이 올바르지 않습니다.")
    candidates = response.get("candidates") or []
    if not candidates:
        raise ValueError("응답에 candidates가 없습니다.")
    for part in (candidates[0].get("content") or {}).get("parts") or []:
        text = part.get("text")
        if text:
            return text
    raise ValueError("응답에 텍스트 파트가 없습니다.")


async def _gateway(prompt: str, document: Document | None) -> tuple[PolicyDecision, dict]:
    parts: list[dict] = [{"text": prompt}]
    if document is not None:
        parts.append(
            {
                "inlineData": {
                    "mimeType": document.mime_type,
                    "data": base64.b64encode(document.data).decode(),
                }
            }
        )

    result = await chain.post(
        "/ai/generate",
        {
            "model": settings.gemini_model,
            "request": {
                "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": RESPONSE_SCHEMA,
                    "temperature": 0.0,
                },
            },
        },
    )

    decision = PolicyDecision.model_validate_json(_answer_text(result.get("response")))
    payment = result.get("payment") or {}
    return decision, {"rail": "gateway", **payment}


async def evaluate_policy(
    prompt: str, document: Document | None
) -> tuple[PolicyDecision, dict]:
    if settings.ai_rail != "gateway":
        return await _direct(prompt, document), {"rail": "direct"}

    try:
        return await _gateway(prompt, document)
    except Exception as failed:
        reason = getattr(failed, "detail", None) or str(failed)

    return await _direct(prompt, document), {
        "rail": "direct",
        "fallbackFrom": "gateway",
        "reason": reason,
    }
