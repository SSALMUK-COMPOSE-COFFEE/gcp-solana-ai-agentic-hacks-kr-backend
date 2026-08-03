import base64
import json
import os
import sys
import time

import base58
import httpx
from nacl.signing import SigningKey

BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:8080")
RPC = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
SERVICE_TOKEN = os.environ["SERVICE_TOKEN"]
FAN_KEYPAIR = os.environ.get("DEMO_FAN_KEYPAIR", "/tmp/demo/fan.json")
CLUSTER = os.environ.get("DEMO_CLUSTER", "devnet")

USDC = 1_000_000
STEP = 0
LINKS: list[tuple[str, str]] = []
FAILURES: list[str] = []


def head(title: str) -> None:
    global STEP
    STEP += 1
    print(f"\n\033[1m[{STEP}] {title}\033[0m")


def info(label: str, value: object) -> None:
    print(f"    {label:<16} {value}")


def link(label: str, signature: str) -> None:
    url = f"https://explorer.solana.com/tx/{signature}?cluster={CLUSTER}"
    LINKS.append((label, url))
    info("tx", url)


def mainnet_link(label: str, kind: str, address: str) -> None:
    url = f"https://explorer.solana.com/{kind}/{address}"
    LINKS.append((label, url))
    info(kind, url)


def expect(label: str, got: int, want: int, detail: str = "") -> None:
    ok = got == want
    mark = "\033[32m✅\033[0m" if ok else "\033[31m❌\033[0m"
    print(f"    {mark} {label:<38} {got} (기대 {want}) {detail}")
    if not ok:
        FAILURES.append(f"{label}: {got} != {want}")


def api(method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.request(method, f"{BASE}{path}", headers=headers, timeout=180, **kw)


def must(response: httpx.Response, what: str) -> dict:
    if response.status_code >= 400:
        print(f"\033[31m{what} 실패: {response.status_code} {response.text[:300]}\033[0m")
        sys.exit(1)
    return response.json()


def load_key(path: str) -> tuple[SigningKey, str]:
    raw = bytes(json.load(open(path)))
    key = SigningKey(raw[:32])
    return key, base58.b58encode(bytes(key.verify_key)).decode()


def rpc(method: str, params: list) -> dict:
    return httpx.post(
        RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=90
    ).json()


def sol_balance(pubkey: str) -> float:
    return rpc("getBalance", [pubkey])["result"]["value"] / 1e9


def read_compact_u16(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, offset
        shift += 7


def countersign(tx_base64: str, key: SigningKey, pubkey: str) -> str:
    raw = bytearray(base64.b64decode(tx_base64))
    count, offset = read_compact_u16(raw, 0)
    sig_start = offset
    message = bytes(raw[sig_start + count * 64 :])

    required = message[0]
    _, keys_offset = read_compact_u16(message, 3)
    signers = [
        base58.b58encode(message[keys_offset + i * 32 : keys_offset + (i + 1) * 32]).decode()
        for i in range(required)
    ]
    index = signers.index(pubkey)

    signature = key.sign(message).signature
    raw[sig_start + index * 64 : sig_start + (index + 1) * 64] = signature
    return base64.b64encode(bytes(raw)).decode()


def send_raw(tx_base64: str) -> str:
    result = rpc("sendTransaction", [tx_base64, {"encoding": "base64", "preflightCommitment": "confirmed"}])
    if "error" in result:
        print(f"\033[31m트랜잭션 전송 실패: {json.dumps(result['error'])[:400]}\033[0m")
        sys.exit(1)
    signature = result["result"]
    for _ in range(60):
        status = rpc("getSignatureStatuses", [[signature]])["result"]["value"][0]
        if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
            return signature
        time.sleep(2)
    print("\033[31m트랜잭션 확정 대기 시간 초과\033[0m")
    sys.exit(1)


def quote_pdf(lines: list[str]) -> bytes:
    text = "BT /F1 13 Tf 60 780 Td 20 TL\n"
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        text += f"({escaped}) Tj T*\n"
    text += "ET"
    stream = text.encode("latin-1", "replace")

    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % number + body + b"endobj\n"

    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)
    return bytes(out)


def main() -> None:
    print("\033[1m팬덤 총대 에이전트 — 온체인 데모\033[0m")
    info("API", BASE)
    info("cluster", CLUSTER)

    fan_key, fan_pubkey = load_key(FAN_KEYPAIR)
    leader_key = SigningKey.generate()
    leader_pubkey = base58.b58encode(bytes(leader_key.verify_key)).decode()
    stamp = base58.b58encode(os.urandom(6)).decode().lower()
    vendor_wallet = base58.b58encode(bytes(SigningKey.generate().verify_key)).decode()
    other_wallet = base58.b58encode(bytes(SigningKey.generate().verify_key)).decode()
    title = f"Keyring Demo Campaign {stamp}"
    vendor_name = "Keyring Factory"

    head("총대 가입 · 지갑 연결")
    auth = must(api("POST", "/auth/signup", json={
        "email": f"demo-{stamp}@example.com", "password": "demo-pass-1234", "name": "총대"}), "가입")
    leader_token = auth["accessToken"]
    nonce = must(api("POST", "/auth/wallet/nonce",
                     json={"walletAddress": leader_pubkey}), "nonce")["nonce"]
    signature = base58.b58encode(leader_key.sign(nonce.encode()).signature).decode()
    must(api("POST", "/auth/wallet/connect", leader_token,
             json={"walletAddress": leader_pubkey, "nonce": nonce, "signature": signature}), "지갑 연결")
    info("총대 지갑", leader_pubkey)

    head("캠페인 생성 (온체인 escrow PDA)")
    campaign = must(api("POST", "/campaign", leader_token, json={
        "title": title,
        "category": "굿즈",
        "goalAmount": 1 * USDC,
        "deadline": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400)),
        "policy": {
            "categories": {"굿즈": {"maxUnitPrice": 1 * USDC, "maxTotal": 3 * USDC, "unitLabel": "개"}},
            "aiReviewBudget": 250_000,
            "allowSurplusScaling": False,
        },
    }), "캠페인 생성")
    cid = campaign["id"]
    info("campaign", cid)
    info("escrow PDA", campaign["escrowPda"])

    tier = must(api("POST", f"/campaign/{cid}/tiers", leader_token, json={
        "title": "키링 세트", "price": 1 * USDC, "items": ["키링"]}), "티어")["tierId"]
    info("리워드 티어", f"{tier} — 1 USDC (구성품: 키링)")

    head("Solana Pay QR 발급")
    qr = must(api("POST", "/payment/solana-pay/qr", leader_token,
                  json={"campaignId": cid, "tierId": tier}), "QR")
    info("reference", qr["reference"])
    info("url", qr["url"][:88] + "…")

    head("팬 기여 — 가스리스 (SOL 0 소모)")
    before = sol_balance(fan_pubkey)
    info("기여 전 SOL", f"{before:.9f}")
    built = must(api("POST", f"/payment/solana-pay/tx?ref={qr['reference']}",
                     json={"account": fan_pubkey}), "트랜잭션 조립")
    signed = countersign(built["transaction"], fan_key, fan_pubkey)
    tx = send_raw(signed)
    link("기여", tx)
    must(api("POST", "/payment/contribute", leader_token,
             json={"reference": qr["reference"], "txSignature": tx}), "기여 확정")
    after = sol_balance(fan_pubkey)
    info("기여 후 SOL", f"{after:.9f}")
    expect("가스리스 — 기여자 SOL 변화 없음", round(after, 9) == round(before, 9), True)

    head("목표 달성 → 마감 (Funding → Executing)")
    closed = must(api("POST", f"/campaign/{cid}/close", leader_token), "마감")
    info("상태", closed["status"])
    link("마감", closed["txSignature"])

    head("벤더 등록 · 견적 제출")
    vendor = must(api("POST", "/vendor", json={
        "name": vendor_name, "category": "굿즈",
        "walletAddress": vendor_wallet, "contact": "contact@keyringfactory.example"}), "벤더 등록")
    vid, vkey = vendor["id"], vendor["apiKey"]
    must(api("POST", f"/vendor/{vid}/allowlist", SERVICE_TOKEN), "allowlist")

    pdf = quote_pdf([
        f"{vendor_name} - Official Quote",
        f"Campaign: {title}",
        "Item: Keyring",
        "Quantity: 1",
        "Unit price: 1.00 USDC",
        "Total: 1.00 USDC",
    ])
    uploaded = must(api("POST", "/proof/upload", headers={"X-Vendor-Key": vkey},
                        files={"file": ("quote.pdf", pdf, "application/pdf")}), "업로드")
    file_url = uploaded["fileUrl"]
    info("견적서", f"{vendor_name} · 키링 1개 × 1.00 USDC")
    quote = must(api("POST", f"/vendor/{vid}/quote", headers={"X-Vendor-Key": vkey}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 1 * USDC, "quantity": 1}],
        "totalAmount": 1 * USDC, "fileUrl": file_url}), "견적 제출")
    pid = quote["proofId"]
    info("proof", f"{pid} — 신고 1 USDC (판매 티어 1개와 수량 일치)")

    spare = must(api("POST", f"/vendor/{vid}/quote", headers={"X-Vendor-Key": vkey}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 1 * USDC, "quantity": 1}],
        "totalAmount": 1 * USDC, "fileUrl": file_url}), "예비 견적")["proofId"]

    selfdeal = must(api("POST", "/vendor", json={
        "name": f"Leader Shop {stamp}", "category": "굿즈",
        "walletAddress": leader_pubkey, "contact": "self@example.com"}), "자기거래 벤더")
    must(api("POST", f"/vendor/{selfdeal['id']}/allowlist", SERVICE_TOKEN), "allowlist3")
    self_status = api("POST", f"/vendor/{selfdeal['id']}/quote",
                      headers={"X-Vendor-Key": selfdeal["apiKey"]}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 1 * USDC, "quantity": 1}],
        "totalAmount": 1 * USDC, "fileUrl": file_url}).status_code

    head("🤖 에이전트 심사 → 자동 집행")
    verdict = must(api("POST", "/agent/policy/evaluate", SERVICE_TOKEN,
                       json={"campaignId": cid, "proofId": pid}), "심사")
    info("판정", verdict["decision"])
    info("파일 판독", verdict["readFile"])
    for reason in verdict["reasons"][:4]:
        print(f"      · {reason}")
    pay = verdict["micropay"]
    if pay.get("paid"):
        if pay.get("rail") == "x402":
            info("AI 심사비", f"예약 {pay['authorized']} raw units — mainnet USDC 실결제")
            mainnet_link("AI 결제 채널", "address", pay["channelId"])
        else:
            info("AI 심사비", f"{pay['amount']} raw units")
            link("micropay", pay["txSignature"])
    execution = verdict.get("execution") or {}
    if execution.get("executed"):
        info("자동 집행", f"{execution['releasedAmount']} raw units → 벤더")
        link("자동 집행", execution["txSignature"])
    else:
        print(f"\033[31m    자동 집행 안 됨: {execution}\033[0m")
        FAILURES.append("자동 집행 실패")
    defenses(cid, pid, vid, vkey, file_url, leader_token, stamp, other_wallet, spare, self_status)


def defenses(cid, pid, vid, vkey, file_url, leader_token, stamp, other_wallet, spare, self_status) -> None:
    head("🔒 방어 시연 — 총대는 자금을 뺄 수 없다")
    body = {"vendorId": vid, "proofId": pid, "amount": 1 * USDC}
    expect("총대 JWT로 집행 시도 (D2)", api("POST", f"/settlement/{cid}/release", leader_token, json=body).status_code, 401)

    other = must(api("POST", "/vendor", json={
        "name": f"다른벤더-{stamp}", "category": "굿즈",
        "walletAddress": other_wallet, "contact": "x@example.com"}), "벤더2")
    must(api("POST", f"/vendor/{other['id']}/allowlist", SERVICE_TOKEN), "allowlist2")
    expect("증빙 벤더A → 벤더B 집행 (D29)", api("POST", f"/settlement/{cid}/release", SERVICE_TOKEN,
        json={"vendorId": other["id"], "proofId": pid, "amount": 1 * USDC}).status_code, 403)
    expect("승인 금액 1 → 9 USDC 조작 (D29)", api("POST", f"/settlement/{cid}/release", SERVICE_TOKEN,
        json={"vendorId": vid, "proofId": pid, "amount": 9 * USDC}).status_code, 400)
    expect("같은 증빙 재집행 (D25)", api("POST", f"/settlement/{cid}/release", SERVICE_TOKEN, json=body).status_code, 409)
    expect("집행된 증빙 재심사 (F5)", api("POST", "/agent/policy/evaluate", SERVICE_TOKEN,
        json={"campaignId": cid, "proofId": pid}).status_code, 409)

    head("🔒 방어 시연 — 증빙 위조·자금 유용")
    inflated = api("POST", f"/vendor/{vid}/quote", headers={"X-Vendor-Key": vkey}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 100_000, "quantity": 2}],
        "totalAmount": 9 * USDC, "fileUrl": file_url})
    expect("항목합계 0.2 ≠ 신고 9 USDC (D30)", inflated.status_code, 400)
    ssrf = api("POST", f"/vendor/{vid}/quote", headers={"X-Vendor-Key": vkey}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 1 * USDC, "quantity": 1}],
        "totalAmount": 1 * USDC, "fileUrl": "http://169.254.169.254/latest/meta-data"})
    expect("증빙 URL에 내부 주소 (D28)", ssrf.status_code, 400)

    expect("총대 지갑 = 벤더 지갑 자기거래 (D22)", self_status, 403)

    receipt = must(api("POST", "/proof/receipt", headers={"X-Vendor-Key": vkey}, json={
        "campaignId": cid, "items": [{"name": "Keyring", "unitPrice": 1 * USDC, "quantity": 1}],
        "totalAmount": 1 * USDC, "fileUrl": file_url}), "영수증")
    expect("영수증으로 집행 시도 (D24)", api("POST", f"/settlement/{cid}/release", SERVICE_TOKEN,
        json={"vendorId": vid, "proofId": receipt["proofId"], "amount": 1 * USDC}).status_code, 409)

    head("🔒 방어 시연 — AI 심사 예산 한도 (D34)")
    settlement = must(api("GET", f"/settlement/{cid}"), "정산")
    info("예산", f"{settlement['aiReviewBudget']} raw units")
    info("사용", f"{settlement['aiReviewCost']} raw units")
    second = api("POST", "/agent/policy/evaluate", SERVICE_TOKEN,
                 json={"campaignId": cid, "proofId": spare})
    expect("예산 소진 후 심사 요청 (D34)", second.status_code, 402, "Gemini 미호출")

    head("정산 요약")
    for label, value in [("모금액", settlement["raisedAmount"]), ("집행액", settlement["releasedAmount"]),
                         ("에스크로 잔액", settlement["remainingInEscrow"]),
                         ("AI 심사 비용", settlement["aiReviewCost"])]:
        info(label, f"{value} raw units ({value / USDC:.2f} USDC)")
    for r in settlement["aiReceipts"]:
        if r.get("rail") == "x402":
            state = "확정" if r["settled"] else "정산 대기"
            info("AI 영수증", f"[mainnet x402/{state}] 채널 {r['channelId']}")
        else:
            info("AI 영수증", r["txSignature"])

    print("\n\033[1m온체인 증빙 (Explorer)\033[0m")
    for label, url in LINKS:
        print(f"    {label:<12} {url}")

    print()
    if FAILURES:
        print(f"\033[31m실패 {len(FAILURES)}건:\033[0m")
        for f in FAILURES:
            print(f"    - {f}")
        sys.exit(1)
    print("\033[32m전 단계 통과\033[0m")


if __name__ == "__main__":
    main()
