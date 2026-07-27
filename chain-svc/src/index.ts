import { serve } from "@hono/node-server";
import anchor from "@coral-xyz/anchor";
import { PublicKey } from "@solana/web3.js";
import { Hono } from "hono";
import { z } from "zod";

import { PAY_ICON, PAY_LABEL, PORT, SOLANA_RPC_URL } from "./config.js";
import {
  buildContributeTransaction,
  findReferenceSignature,
  newReference,
  paymentUrl,
} from "./pay.js";
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

app.get("/pay/reference/:ref", async (c) => {
  const reference = c.req.param("ref");
  const txSignature = await findReferenceSignature(reference);
  return c.json({
    reference,
    status: txSignature ? "confirmed" : "pending",
    txSignature,
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

  const cached = idempotencyCache.get(body.idemKey);
  if (cached) {
    return c.json({ signature: cached, replayed: true });
  }

  const signature = await release(body.campaignUuid, body.vendorWallet, body.amount);
  idempotencyCache.set(body.idemKey, signature);

  return c.json({
    signature,
    replayed: false,
    status: await campaignStatus(body.campaignUuid),
  });
});

const RefundBatchBody = z.object({ campaignUuid: z.string().uuid() });

app.post("/tx/refund-batch", async (c) => {
  const body = RefundBatchBody.parse(await c.req.json());
  return c.json(await refundBatch(body.campaignUuid));
});

app.post("/nft/certificate", async (c) => c.json({ todo: "cnft mint" }, 501));

serve({ fetch: app.fetch, port: PORT }, (info) => {
  console.log(
    `chain-svc listening on :${info.port} (rpc: ${SOLANA_RPC_URL}, agent: ${agentAuthority.publicKey.toBase58()})`
  );
});
