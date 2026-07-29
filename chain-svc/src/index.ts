import { serve } from "@hono/node-server";
import anchor from "@coral-xyz/anchor";
import { PublicKey } from "@solana/web3.js";
import { Hono } from "hono";
import { z } from "zod";

import { GEMINI_GATEWAY_URL, PAY_ICON, PAY_LABEL, PORT, SOLANA_RPC_URL } from "./config.js";
import { fetchWithPayment } from "./x402/client.js";
import {
  buildContributeTransaction,
  findReferenceSignature,
  newReference,
  paymentUrl,
} from "./pay.js";
import { micropay } from "./paysh.js";
import { campaignStatus, closeCampaign, refundBatch, release } from "./settlement.js";
import {
  accountExists,
  agentAuthority,
  campaignPdaFor,
  escrowAtaFor,
  program,
  usdcMint,
  uuidToBytes,
} from "./solana.js";

const { BN } = anchor;

const app = new Hono();

const idempotencyCache = new Map<string, string>();
const inflight = new Map<string, Promise<string>>();

async function onceByKey(idemKey: string, run: () => Promise<string>) {
  const cached = idempotencyCache.get(idemKey) ?? (await inflight.get(idemKey));
  if (cached) return { signature: cached, replayed: true };

  const task = run().then((signature) => {
    idempotencyCache.set(idemKey, signature);
    return signature;
  });
  inflight.set(idemKey, task);
  try {
    return { signature: await task, replayed: false };
  } finally {
    inflight.delete(idemKey);
  }
}

app.onError((err, c) => {
  if (err instanceof z.ZodError) {
    return c.json({ message: "유효하지 않은 입력값입니다." }, 400);
  }
  console.error(err);
  return c.json({ message: err.message }, 500);
});

app.get("/health", (c) =>
  c.json({
    status: "ok",
    rpc: SOLANA_RPC_URL,
    programId: program.programId.toBase58(),
    agentAuthority: agentAuthority.publicKey.toBase58(),
    usdcMint: usdcMint.toBase58(),
  })
);

const CreateCampaignBody = z.object({
  idemKey: z.string().uuid(),
  authority: z.string(),
  goalAmount: z.coerce.bigint().positive(),
  deadline: z.number().int(),
});

app.post("/tx/campaign", async (c) => {
  const body = CreateCampaignBody.parse(await c.req.json());

  const uuidBytes = uuidToBytes(body.idemKey);
  const campaignPda = campaignPdaFor(uuidBytes);
  const escrowPda = escrowAtaFor(campaignPda);
  const addresses = {
    campaignPda: campaignPda.toBase58(),
    escrowPda: escrowPda.toBase58(),
  };

  if (await accountExists(campaignPda)) {
    return c.json({
      ...addresses,
      signature: idempotencyCache.get(body.idemKey) ?? null,
      created: false,
    });
  }

  try {
    const signature = await program.methods
      .createCampaign(uuidBytes, new BN(body.goalAmount.toString()), new BN(body.deadline))
      .accounts({
        authority: new PublicKey(body.authority),
        agentAuthority: agentAuthority.publicKey,
        usdcMint,
      })
      .rpc();

    idempotencyCache.set(body.idemKey, signature);
    return c.json({ ...addresses, signature, created: true }, 201);
  } catch (err) {
    if (await accountExists(campaignPda)) {
      return c.json({
        ...addresses,
        signature: idempotencyCache.get(body.idemKey) ?? null,
        created: false,
      });
    }
    throw err;
  }
});

app.post("/pay/url", async (c) => {
  const reference = newReference();
  return c.json({ reference, url: paymentUrl(reference) }, 201);
});

app.get("/pay/tx", (c) => c.json({ label: PAY_LABEL, icon: PAY_ICON }));

const PayTxBody = z.object({
  account: z.string(),
  campaignUuid: z.string().uuid(),
  amount: z.coerce.bigint().positive(),
  reference: z.string(),
});

app.post("/pay/tx", async (c) => {
  const body = PayTxBody.parse(await c.req.json());
  const transaction = await buildContributeTransaction(
    body.campaignUuid,
    body.amount,
    body.reference,
    body.account
  );
  const usdc = (Number(body.amount) / 1_000_000).toLocaleString("en-US");
  return c.json({ transaction, message: `${PAY_LABEL} — ${usdc} USDC 기여` });
});

const ReferenceQuery = z.object({
  campaignUuid: z.string().uuid(),
  amount: z.coerce.bigint().positive(),
});

app.get("/pay/reference/:ref", async (c) => {
  const reference = c.req.param("ref");
  const query = ReferenceQuery.parse(c.req.query());
  const { txSignature, reason } = await findReferenceSignature(
    reference,
    query.campaignUuid,
    query.amount
  );
  return c.json({
    reference,
    status: txSignature ? "confirmed" : "pending",
    txSignature,
    reason,
  });
});

const CloseBody = z.object({ campaignUuid: z.string().uuid() });

app.post("/tx/close", async (c) => {
  const { campaignUuid } = CloseBody.parse(await c.req.json());
  const signature = await closeCampaign(campaignUuid);
  return c.json({ signature, status: await campaignStatus(campaignUuid) });
});

const ReleaseBody = z.object({
  idemKey: z.string().uuid(),
  campaignUuid: z.string().uuid(),
  vendorWallet: z.string(),
  amount: z.coerce.bigint().positive(),
});

app.post("/tx/release", async (c) => {
  const body = ReleaseBody.parse(await c.req.json());

  const { signature, replayed } = await onceByKey(body.idemKey, () =>
    release(body.campaignUuid, body.vendorWallet, body.amount)
  );

  return c.json({
    signature,
    replayed,
    status: await campaignStatus(body.campaignUuid),
  });
});

const RefundBatchBody = z.object({ campaignUuid: z.string().uuid() });

app.post("/tx/refund-batch", async (c) => {
  const body = RefundBatchBody.parse(await c.req.json());
  return c.json(await refundBatch(body.campaignUuid));
});

const MicropayBody = z.object({
  idemKey: z.string().uuid(),
  amount: z.coerce.bigint().positive(),
});

app.post("/tx/micropay", async (c) => {
  const body = MicropayBody.parse(await c.req.json());

  const cached = idempotencyCache.get(body.idemKey);
  if (cached) {
    return c.json({ paid: true, signature: cached, reason: null, replayed: true });
  }

  const result = await micropay(body.amount);
  if (result.signature) {
    idempotencyCache.set(body.idemKey, result.signature);
  }
  return c.json(result);
});

const AiGenerateBody = z.object({
  model: z.string(),
  request: z.record(z.unknown()),
});

app.post("/ai/generate", async (c) => {
  const body = AiGenerateBody.parse(await c.req.json());
  const url = `${GEMINI_GATEWAY_URL}/v1beta/models/${body.model}:generateContent`;

  const result = await fetchWithPayment(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body.request),
  });

  if (result.status >= 400) {
    return c.json({ message: "게이트웨이 호출에 실패했습니다.", detail: result.body }, 502);
  }

  return c.json({
    response: result.body,
    payment: {
      authorized: result.authorized,
      settled: result.settled,
      channelId: result.channelId,
    },
  });
});

app.post("/nft/certificate", async (c) => c.json({ todo: "cnft mint" }, 501));

serve({ fetch: app.fetch, port: PORT }, (info) => {
  console.log(
    `chain-svc listening on :${info.port} (rpc: ${SOLANA_RPC_URL}, agent: ${agentAuthority.publicKey.toBase58()})`
  );
});
