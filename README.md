# 총대 (Chongdae) — 팬덤 에스크로 에이전트 · 백엔드

> **신뢰하는 사람 → 검증하는 프로토콜**
> 총대의 '집행 버튼'을 없앤 팬덤 공동 프로젝트 플랫폼. 모금부터 집행·환불까지 Solana 에스크로가 보관하고, Gemini 에이전트가 정책대로 자율 집행합니다.

**GCP × Solana AI Agentic Hacks KR 제출작** · 프론트엔드 저장소는 [gcp-solana-ai-agentic-hacks-kr-frontend](https://github.com/SSALMUK-COMPOSE-COFFEE/gcp-solana-ai-agentic-hacks-kr-frontend)


|                  |                                                                                                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| 서비스              | [https://chongdae.hajin.xyz](https://chongdae.hajin.xyz)                                                                                          |
| API 문서 (Swagger) | [https://chongdae.hajin.xyz/api/docs](https://chongdae.hajin.xyz/api/docs)                                                                        |
| 인프라              | Google Cloud — Cloud Run · Cloud SQL · Cloud Storage · Secret Manager                                                                             |
| 체인               | Solana **devnet** (캠페인 자금) · Solana **mainnet** (x402 AI 심사비)                                                                                     |
| Escrow 프로그램      | [`5QzRtGsFnLRmmMPygmSf5HkLP4cKzNbyMBtM2zx4cS2n`](https://explorer.solana.com/address/5QzRtGsFnLRmmMPygmSf5HkLP4cKzNbyMBtM2zx4cS2n?cluster=devnet) |


---

## 1. 무엇을 해결하나

생일카페·지하철 광고 같은 팬덤 공동 프로젝트는 '총대' 한 명이 대표로 모금하고 대표로 집행합니다. 모금액은 개인 계좌로 들어가고, 정산 공지는 스크린샷 몇 장이 전부이며, 벤더 견적서의 진위는 아무도 대조하지 않습니다.

이 프로젝트는 **총대에게서 집행 권한 자체를 제거**합니다.

- 자금은 온체인 에스크로(PDA)가 보관합니다.
- 집행·환불 인스트럭션에는 `has_one = agent_authority` 제약이 걸려 있어 **총대 서명으로는 실행 자체가 불가능**합니다.
- 집행 API(`POST /settlement/{id}/release`)는 에이전트 service token 전용이라, 총대가 자기 JWT로 호출하면 **401**을 받습니다.
- 에이전트는 Gemini로 증빙 파일을 직접 판독해 신고값과 대조하고, 승인 시 **같은 요청 안에서 온체인 release까지** 실행합니다.

---

## 2. 아키텍처

```
      웹 SPA (별도 저장소)
            │  HTTPS
            ▼
┌───────────────────────────────────────────────┐
│  Cloud Run 서비스 (chongdae-api)               │
│                                               │
│  ┌─────────────────┐   HTTP   ┌─────────────┐ │
│  │ api  :8080      │─────────▶│ chain-svc   │ │
│  │ Python 3.13     │ localhost│  :8081      │ │
│  │ FastAPI         │   :8081  │ Node 22     │ │
│  │                 │          │ Hono · TS   │ │
│  │ 도메인 로직        │          │             │ │
│  │ 룰 정책 엔진       │          │ Anchor 클라  │ │
│  │ Gemini 심사      │          │ Solana Pay  │ │
│  │ JWT/서명 인증     │          │ x402 채널    │ │
│  └────────┬────────┘          └──────┬──────┘ │
│           │ unix socket              │        │
└───────────┼──────────────────────────┼────────┘
            ▼                          ▼
      Cloud SQL                   Solana
      (Postgres 17)         devnet escrow / mainnet x402
```

**왜 2개로 쪼갰나** — 분할 기준은 *레퍼런스 구현 언어*입니다. Gemini SDK와 도메인 로직은 Python이, Anchor·Solana Pay·x402는 TypeScript가 1급 시민입니다. 경계 통신은 HTTP/JSON을 쓰는데, 병목이 Solana RPC라 gRPC 이득이 없습니다.

**키 경계** — agent_authority 키페어와 x402 mainnet 키페어는 **chain-svc 컨테이너에만** 읽기 전용으로 마운트됩니다. Python api는 서명 키를 알지 못하며, 온체인 서명은 전부 chain-svc를 거칩니다. Cloud Run에서는 Secret Manager → 사이드카 볼륨으로 같은 경계가 유지됩니다.

### 저장소 구조

```
api/                 Python 3.13 · FastAPI — 도메인 · 51 엔드포인트
  app/core/          설정, DB, 인증, 정책 엔진, Gemini, 정산, 스토리지
  app/models/        SQLModel 테이블 (12개)
  app/routers/       auth · campaign · payment · proof · settlement · vendor · agent · users · files · webhook
  app/schemas/       요청/응답 Pydantic 스키마
chain-svc/           Node 22 · Hono · TS — stateless 온체인 사이드카 (DB 미접속)
  src/x402/          x402 'upto' 결제 채널 직접 구현 (공개 클라이언트에 upto 스킴이 없어 자작)
  src/idl/           Anchor IDL
program/             Anchor(Rust) escrow 프로그램 + 테스트 8건
demo/                E2E 데모 스크립트 (본편 7단계 + 방어 시연 10건)
deploy/cloudrun/     Cloud Run 서비스 매니페스트 · LB URL 맵
deploy/nginx/        (구) 개인 서버 리버스 프록시 설정
```

---

## 3. 로컬에서 실행하기

### 사전 준비물

- **Docker / Docker Compose** — 이것만 있으면 API는 뜹니다.
- **Solana CLI** — 키페어 생성용. [설치](https://docs.solanalabs.com/cli/install)
- **Gemini API 키** — [Google AI Studio](https://aistudio.google.com/apikey)에서 발급 (무료 티어로 충분합니다)
- (선택) **Anchor 0.31.1 + Rust** — 온체인 프로그램을 직접 빌드/배포할 때만. 프로그램은 이미 devnet에 배포돼 있어 필요 없습니다.

### 1) 키페어 준비

chain-svc는 두 개의 키페어를 마운트합니다. 없으면 컨테이너가 뜨지 않습니다.

```bash
mkdir -p ~/.keys/chongdae/demo

# 에이전트 권한 키 (devnet) — 캠페인 생성·집행·환불 서명 + 기여 가스 대납
solana-keygen new --no-bip39-passphrase -o ~/.keys/chongdae/agent-authority.json
solana airdrop 2 $(solana-keygen pubkey ~/.keys/chongdae/agent-authority.json) --url devnet

# x402 결제 키 (mainnet) — AI 심사비 실결제용
solana-keygen new --no-bip39-passphrase -o ~/.keys/chongdae/agent-mainnet.json

# 데모용 팬 지갑 (devnet) — E2E 스크립트에서 기여자 역할
solana-keygen new --no-bip39-passphrase -o ~/.keys/chongdae/demo/fan.json
solana airdrop 2 $(solana-keygen pubkey ~/.keys/chongdae/demo/fan.json) --url devnet
```

팬 지갑에는 **devnet USDC**가 필요합니다. Circle 공식 devnet mint(`4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`)를 [Circle faucet](https://faucet.circle.com/)에서 받으세요.

> **AI_RAIL=gateway(mainnet x402 실결제)로 돌리려면** `agent-mainnet.json` 주소에 실제 USDC가 소액(0.5 USDC 정도면 충분) 있어야 합니다. 없으면 아래 `.env`에서 `AI_RAIL=direct`로 두세요 — Gemini를 직접 호출하고 심사비는 devnet micropay로 처리합니다.

### 2) 환경변수

```bash
cp .env.example .env
```

`.env`를 아래처럼 채웁니다. **`ROOT_PATH`는 로컬에서 반드시 비워두세요** — 값이 있으면 Swagger UI가 `/api/openapi.json`을 찾다가 404가 납니다(프로덕션은 LB가 `/api` 프리픽스를 붙이므로 `/api`를 씁니다).

```bash
POSTGRES_USER=app
POSTGRES_PASSWORD=<임의의 문자열>
POSTGRES_DB=chongdae
DATABASE_URL=postgresql+asyncpg://app:<위와 동일>@db:5432/chongdae

JWT_SECRET=<openssl rand -hex 32>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_TTL=3600
REFRESH_TOKEN_TTL=1209600
NONCE_TTL=300

SERVICE_TOKEN=<openssl rand -hex 24>   # 에이전트 전용 API 토큰

ROOT_PATH=                              # 로컬은 비워둘 것
APP_VERSION=0.1.0
PUBLIC_BASE_URL=http://localhost:8090

CHAIN_SVC_URL=http://chain-svc:8081     # compose 네트워크 기준
CHAIN_SVC_PORT=8081
CHAIN_ENABLED=true
CHAIN_SVC_TIMEOUT=60

STORAGE_BACKEND=local
STORAGE_DIR=/data/uploads
STORAGE_PUBLIC_BASE_URL=http://localhost:8090/static

SOLANA_RPC_URL=https://api.devnet.solana.com
USDC_MINT=4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU

PAY_LABEL=팬덤 총대 에이전트
PAY_ICON=http://localhost:8090/static/icon.png

GEMINI_API_KEY=<AI Studio 키>
GEMINI_MODEL=gemini-3.5-flash-lite

AI_RAIL=direct                          # gateway = mainnet x402 실결제
GEMINI_GATEWAY_URL=https://generativelanguage.google.gateway-402.com
X402_ASSET=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
X402_MAINNET_RPC_URL=https://api.mainnet-beta.solana.com
```

### 3) 기동

```bash
docker compose up -d --build
docker compose logs -f api
```


| 대상         | 주소                                                       |
| ---------- | -------------------------------------------------------- |
| API        | [http://localhost:8090](http://localhost:8090)           |
| Swagger UI | [http://localhost:8090/docs](http://localhost:8090/docs) |
| Postgres   | `127.0.0.1:5434` (로컬 바인딩)                                |
| chain-svc  | 컨테이너 내부 전용 — 외부 노출 없음                                    |


테이블은 기동 시 `SQLModel.create_all`로 자동 생성됩니다. 마이그레이션 도구는 쓰지 않습니다 — 스키마를 바꾸면 `docker compose down -v`로 볼륨을 지우거나 직접 `ALTER TABLE` 하세요.

### 4) 동작 확인

```bash
curl http://localhost:8090/health
curl http://localhost:8090/campaign
```

---

## 4. E2E 데모 스크립트

`demo/run_demo.py`는 **본편 7단계 + 방어 시연 10건**을 한 번에 재현합니다. 영상 대본이자 회귀 테스트로 쓰고 있으며, 하나라도 기대와 다르면 `exit 1`입니다.

```bash
./demo/run_demo.sh
```

실행 내용:


| #    | 단계                 | 검증                            |
| ---- | ------------------ | ----------------------------- |
| 1    | 총대 가입 · 지갑 연결      | ed25519 서명 인증                 |
| 2    | 캠페인 생성             | 온체인 escrow PDA 생성             |
| 3    | Solana Pay QR 발급   | Transaction Request 조립        |
| 4    | 팬 기여               | **가스리스 — 기여자 SOL 잔고 변화 0 실측** |
| 5    | 목표 달성 → 마감         | Funding → Executing 온체인 전이    |
| 6    | 벤더 등록 · 견적서 PDF 제출 | API 키 + allowlist             |
| 7    | 에이전트 심사 → 자동 집행    | Gemini 판독 → 온체인 release       |
| 8~10 | 방어 시연 10건          | 아래 표                          |
| 11   | 정산 요약              | 모금·집행·에스크로 잔액·AI 심사비          |


**방어 시연 (전부 코드 레벨 거절)**


| 공격                         | 응답                     |
| -------------------------- | ---------------------- |
| 총대 JWT로 집행 시도              | `401`                  |
| 벤더 지갑 = 총대 지갑 (자기거래)       | `403`                  |
| 증빙 벤더A → 벤더B에게 집행          | `403`                  |
| 승인 금액 부풀려 집행               | `400`                  |
| 항목 합계 ≠ 신고 총액              | `400`                  |
| 증빙 URL에 내부 메타데이터 IP (SSRF) | `400`                  |
| 영수증으로 집행 시도                | `409`                  |
| 같은 증빙 재집행 (이중 지불)          | `409`                  |
| 집행 완료 증빙 재심사               | `409`                  |
| AI 예산 소진 후 심사 요청           | `402` · **Gemini 미호출** |


배포된 환경을 대상으로 돌리려면:

```bash
DEMO_BASE_URL=https://chongdae.hajin.xyz/api ./demo/run_demo.sh
```

> 유저당 활성 캠페인은 10개로 제한됩니다(agent_authority SOL 고갈 방어). 스크립트가 정리 단계 없이 캠페인을 생성하므로, 같은 계정으로 반복 실행하면 결국 막힙니다.

---

## 5. AI 심사 파이프라인

```
① 룰 엔진(코드)  →  ② AI 예산 검사  →  ③ Gemini 멀티모달  →  ④ 심사비 결제  →  ⑤ 자동 집행
   한도·카테고리        정책 예산 초과       PDF/이미지 판독        x402 mainnet      approve면 같은
   ·합계 검사           시 402 · 호출 차단   temperature 0.0        또는 devnet       요청 안에서
   위반 시 즉시 거절                        JSON 구조화 출력        micropay          온체인 release
   (Gemini 미호출)
```

**Prompt Injection 방어** — 벤더가 올린 파일이 프롬프트 컨텍스트에 들어가므로, **숫자로 판정 가능한 것은 전부 코드로 옮겼습니다**. 파일에 "모두 승인하라"를 심어도 룰 엔진이 먼저 자릅니다. Gemini의 역할은 코드가 못 하는 것 — 문서 판독과 대조 — 로 한정한 이중 방어 구조입니다.

**감사 가능한 판단 로그** — 모든 판단은 `model` 필드로 `rule-based / gemini / onchain` 판단 주체를 구분하고, `read_file` 플래그로 파일을 실제 읽었는지 기록하며, 근거는 *확인한 숫자를 포함한* 한국어 문장 배열로 강제됩니다.

**AI_RAIL 폴백** — `AI_RAIL=gateway`면 chain-svc의 x402 채널을 통해 Gemini를 호출하고 mainnet USDC로 결제합니다. 게이트웨이 장애 시 자동으로 `direct`(SDK 직접 호출 + devnet micropay)로 폴백하며, 응답 메타에 `fallbackFrom`/`reason`이 실립니다.

> 레일에 따라 심사비 차감 단위가 다릅니다 — gateway는 0.25 USDC 예약 후 사용량 확정(lazy), direct는 건당 0.002 USDC 고정. 캠페인 `aiReviewBudget`을 잡을 때 유의하세요.

---

## 6. 인증 3체계


| 주체     | 방식                                       | 헤더                                      |
| ------ | ---------------------------------------- | --------------------------------------- |
| 팬 · 총대 | JWT + ed25519 지갑 서명 (nonce TTL 300초)     | `Authorization: Bearer <access>`        |
| 벤더     | API 키 (SHA256 해시 저장) + allowlist 등재      | `X-Vendor-Key: <key>`                   |
| 에이전트   | service token + 온체인 `agent_authority` 서명 | `Authorization: Bearer <SERVICE_TOKEN>` |


집행(`release`)·환불(`refund`)·allowlist 승인은 **에이전트 전용**입니다. 총대 JWT로는 호출할 수 없습니다.

---

## 7. 온체인 프로그램

Anchor 프로그램은 이미 devnet에 배포돼 있습니다. 직접 빌드·테스트하려면:

```bash
cd program
anchor build
anchor test          # 8/8 통과 — "총대 서명 집행 불가" 케이스 포함
```


| 인스트럭션             | 설명                                 | 서명자                    |
| ----------------- | ---------------------------------- | ---------------------- |
| `create_campaign` | Campaign PDA + escrow ATA 생성       | agent                  |
| `contribute`      | 기여자 USDC → 에스크로, 기여 PDA 누적         | 기여자 (feePayer = agent) |
| `close_campaign`  | Funding → Executing / Refunding 판정 | agent                  |
| `release`         | 에스크로 → 벤더                          | **agent 전용**           |
| `refund`          | 에스크로 → 기여자                         | **agent 전용**           |


**Solana Pay는 Transfer가 아닌 Transaction Request입니다.** 단순 송금이면 기여자별 온체인 기록이 남지 않아 비율 환불이 성립하지 않습니다. 서버가 `contribute` 인스트럭션을 조립하고 `feePayer = agent_authority`로 부분서명해 지갑에 전달하므로, 기여자는 **SOL 없이** 참여할 수 있습니다.

**가짜 기여 차단** — reference 폴링만으로는 5,000 lamports 송금으로 위조가 가능합니다. ① 성공 트랜잭션 ② escrow 프로그램 실제 호출 ③ **에스크로 ATA 잔액 델타 ≥ 기대 금액**까지 3단으로 검증합니다.

---

## 8. Google Cloud 배포

프로덕션은 **Cloud Run 사이드카** 구조입니다. `api`가 ingress, `chain-svc`가 `localhost:8081`에 붙는 사이드카로 외부에 노출되지 않습니다.

```bash
# 1) 이미지 빌드 · 푸시
REG=asia-northeast3-docker.pkg.dev/<PROJECT>/chongdae
docker build --platform linux/amd64 -t $REG/api:v1 ./api        && docker push $REG/api:v1
docker build --platform linux/amd64 -t $REG/chain-svc:v1 ./chain-svc && docker push $REG/chain-svc:v1

# 2) 시크릿 등록 (Secret Manager)
gcloud secrets create jwt-secret            --data-file=-   # 이하 동일하게
#   database-url · jwt-secret · service-token · gemini-api-key · webhook-secret
#   agent-authority-keypair · agent-mainnet-keypair  ← 키페어는 chain-svc에만 파일 마운트

# 3) 서비스 배포
gcloud run services replace deploy/cloudrun/api-service.yaml --region=asia-northeast3

# 4) LB URL 맵 (/api/* → api, / → web)
gcloud compute url-maps import chongdae-um --source=deploy/cloudrun/url-map.yaml --global
```


| 항목   | 구성                                                                   |
| ---- | -------------------------------------------------------------------- |
| DB   | Cloud SQL Postgres 17 — unix socket (`/cloudsql/...`)                |
| 업로드  | Cloud Storage — gcsfuse 볼륨을 `/data/uploads`에 마운트 (**스토리지 코드 변경 0줄**) |
| 시크릿  | Secret Manager — 키페어 2개는 사이드카 컨테이너에만                                 |
| 인스턴스 | **min=max=1 고정**                                                     |


> **인스턴스를 1로 고정하는 이유**: chain-svc의 온체인 호출 멱등키가 인메모리(`onceByKey`)입니다. 스케일 아웃하면 같은 요청이 두 인스턴스에서 각각 서명될 수 있어 이중 지급 위험이 있습니다. 다중화하려면 멱등키를 외부 저장소로 빼야 합니다.

로컬 → Cloud Run 이전에 필요했던 코드 변경은 **2줄**이었습니다: `api/Dockerfile`의 `$PORT` 대응, 그리고 `CHAIN_SVC_URL`을 `http://localhost:8081`로 바꾼 환경변수 한 줄. 사이드카 경계를 개발 단계에 설계해 둔 결과입니다.

---

## 9. 환경변수


| 이름                                                         | 설명                                  | 예시                                                                  |
| ---------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------- |
| `DATABASE_URL`                                             | Postgres 접속 문자열 (asyncpg)           | `postgresql+asyncpg://app:pw@db:5432/chongdae`                      |
| `JWT_SECRET`                                               | JWT 서명 키                            | `openssl rand -hex 32`                                              |
| `JWT_ALGORITHM` / `ACCESS_TOKEN_TTL` / `REFRESH_TOKEN_TTL` | 토큰 정책                               | `HS256` / `3600` / `1209600`                                        |
| `NONCE_TTL`                                                | 지갑 서명 nonce 유효기간(초)                 | `300`                                                               |
| `SERVICE_TOKEN`                                            | 에이전트 전용 API 토큰                      | `openssl rand -hex 24`                                              |
| `ROOT_PATH`                                                | 리버스 프록시 프리픽스 — **로컬은 비움**           | `` / `/api`                                                         |
| `PUBLIC_BASE_URL`                                          | 외부 공개 기준 URL                        | `https://chongdae.hajin.xyz/api`                                    |
| `CHAIN_SVC_URL`                                            | 사이드카 주소                             | compose `http://chain-svc:8081` · Cloud Run `http://localhost:8081` |
| `CHAIN_ENABLED`                                            | 온체인 호출 on/off                       | `true`                                                              |
| `CHAIN_SVC_TIMEOUT`                                        | 체인 호출 타임아웃(초)                       | `60`                                                                |
| `STORAGE_BACKEND` / `STORAGE_DIR`                          | 증빙 파일 저장 (12MB 상한)                  | `local` / `/data/uploads`                                           |
| `SOLANA_RPC_URL`                                           | devnet RPC                          | `https://api.devnet.solana.com`                                     |
| `USDC_MINT`                                                | devnet USDC mint                    | `4zMMC9...ncDU`                                                     |
| `PAY_LABEL` / `PAY_ICON`                                   | Solana Pay 표시 정보                    | —                                                                   |
| `GEMINI_API_KEY` / `GEMINI_MODEL`                          | AI 심사                               | `gemini-3.5-flash-lite`                                             |
| `AI_RAIL`                                                  | `gateway`(x402 mainnet) 또는 `direct` | `direct`                                                            |
| `GEMINI_GATEWAY_URL`                                       | x402 게이트웨이                          | —                                                                   |
| `X402_KEYPAIR` / `X402_ASSET` / `X402_MAINNET_RPC_URL`     | mainnet 결제 채널                       | —                                                                   |
| `WEBHOOK_SECRET`                                           | 결제 웹훅 서명 검증                         | `openssl rand -hex 32`                                              |
| `PAYSH_TREASURY`                                           | 심사비 수취 주소                           | —                                                                   |

