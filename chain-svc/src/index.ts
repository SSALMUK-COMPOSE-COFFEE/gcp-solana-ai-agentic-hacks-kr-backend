import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { z } from "zod";

const app = new Hono();

const PORT = Number(process.env.PORT ?? 8081);
const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";
const USDC_MINT = process.env.USDC_MINT ?? "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";

const idempotencyCache = new Map<string, string>();

app.get("/health", (c) => c.json({ status: "ok", rpc: SOLANA_RPC_URL }));


const CreateCampaignBody = z.object({
  idemKey: z.string().uuid(),
  authority: z.string(),
  goalAmount: z.coerce.bigint().positive(),
  deadline: z.number().int(),
});

app.post("/tx/campaign", async (c) => {
  const body = CreateCampaignBody.parse(await c.req.json());
  return c.json({ todo: "create_campaign", idemKey: body.idemKey }, 501);
});

app.get("/pay/tx", (c) =>
  c.json({ label: "팬덤 총대 에이전트", icon: "https://hajin.xyz/icon.png" })
);

const PayTxBody = z.object({ account: z.string() });

app.post("/pay/tx", async (c) => {
  const ref = c.req.query("ref");
  const { account } = PayTxBody.parse(await c.req.json());
  return c.json({ todo: "contribute tx", ref, account }, 501);
});

app.post("/pay/url", async (c) => c.json({ todo: "solana-pay url" }, 501));

app.get("/pay/reference/:ref", async (c) =>
  c.json({ todo: "poll reference", ref: c.req.param("ref") }, 501)
);

app.post("/tx/release", async (c) => c.json({ todo: "release" }, 501));

app.post("/tx/refund-batch", async (c) => c.json({ todo: "refund batch" }, 501));

app.post("/nft/certificate", async (c) => c.json({ todo: "cnft mint" }, 501));

serve({ fetch: app.fetch, port: PORT }, (info) => {
  console.log(`chain-svc listening on :${info.port} (rpc: ${SOLANA_RPC_URL}, usdc: ${USDC_MINT})`);
});
