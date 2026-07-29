import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";

import { Keypair, PublicKey } from "@solana/web3.js";

import { X402_ASSET, X402_KEYPAIR } from "../config.js";
import { buildSignedOpenTransaction, channelPda } from "./channel.js";
import type { OpenChannelParams } from "./channel.js";

export interface ChallengeAccept {
  scheme: string;
  network: string;
  amount: string;
  asset: string;
  payTo: string;
  maxTimeoutSeconds?: number;
  extra: {
    tokenProgram: string;
    feePayer: string;
    receiverAuthorizer: string;
    withdrawDelay: number;
    recentBlockhash: string;
    recentSlot: string;
  };
}

export interface Challenge {
  x402Version: number;
  accepts: ChallengeAccept[];
}

export interface PaidResponse {
  status: number;
  body: unknown;
  authorized: string | null;
  settled: string | null;
  channelId: string | null;
  paymentResponse: unknown;
}

let cached: Keypair | null = null;

export function payerKeypair(): Keypair {
  if (!cached) {
    cached = Keypair.fromSecretKey(
      Uint8Array.from(JSON.parse(readFileSync(X402_KEYPAIR, "utf8")))
    );
  }
  return cached;
}

export function parseChallenge(header: string): Challenge {
  const padded = header + "=".repeat((4 - (header.length % 4)) % 4);
  return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
}

export function selectAccept(challenge: Challenge, asset = X402_ASSET): ChallengeAccept {
  const accept = challenge.accepts.find(
    (entry) => entry.scheme === "upto" && entry.asset === asset
  );
  if (!accept) {
    const offered = challenge.accepts.map((e) => `${e.scheme}:${e.asset}`).join(", ");
    throw new Error(`지원하는 결제 수단이 없습니다 (게이트웨이 제공: ${offered})`);
  }
  return accept;
}

export function buildPaymentHeader(challenge: Challenge, accept: ChallengeAccept): {
  header: string;
  channelId: string;
} {
  const payer = payerKeypair();
  const salt = randomBytes(8).readBigUInt64LE();
  const amount = BigInt(accept.amount);

  const params: OpenChannelParams = {
    payer: payer.publicKey,
    feePayer: new PublicKey(accept.extra.feePayer),
    mint: new PublicKey(accept.asset),
    authorizedSigner: new PublicKey(accept.extra.receiverAuthorizer),
    tokenProgram: new PublicKey(accept.extra.tokenProgram),
    recipients: [{ recipient: new PublicKey(accept.payTo), bps: 10000 }],
    salt,
    deposit: amount,
    gracePeriod: accept.extra.withdrawDelay,
    openSlot: BigInt(accept.extra.recentSlot),
  };

  const [channel] = channelPda(params);
  const openTransaction = buildSignedOpenTransaction(
    params,
    accept.extra.recentBlockhash,
    payer
  );

  const now = Math.floor(Date.now() / 1000);
  const payload = {
    authorizedSigner: accept.extra.receiverAuthorizer,
    channelId: channel.toBase58(),
    deposit: amount.toString(),
    expiresAt: now + (accept.maxTimeoutSeconds ?? 300),
    from: payer.publicKey.toBase58(),
    maxAmount: amount.toString(),
    nonce: salt.toString(),
    openSlot: accept.extra.recentSlot,
    openTransaction,
    validAfter: now - 5,
  };

  const envelope = {
    x402Version: challenge.x402Version,
    scheme: accept.scheme,
    network: accept.network,
    accepted: accept,
    payload,
  };

  return {
    header: Buffer.from(JSON.stringify(envelope), "utf8").toString("base64"),
    channelId: channel.toBase58(),
  };
}

function decodeSettled(header: string | null): { response: unknown; settled: string | null } {
  if (!header) return { response: null, settled: null };
  try {
    const padded = header + "=".repeat((4 - (header.length % 4)) % 4);
    const decoded = JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
    const settled =
      decoded?.settledAmount ?? decoded?.amount ?? decoded?.payload?.settledAmount ?? null;
    return { response: decoded, settled: settled === null ? null : String(settled) };
  } catch {
    return { response: header, settled: null };
  }
}

export async function fetchWithPayment(
  url: string,
  init: RequestInit
): Promise<PaidResponse> {
  const first = await fetch(url, init);
  if (first.status !== 402) {
    return {
      status: first.status,
      body: await first.json().catch(() => null),
      authorized: null,
      settled: null,
      channelId: null,
      paymentResponse: null,
    };
  }

  const header = first.headers.get("payment-required");
  if (!header) {
    throw new Error("402 응답에 payment-required 헤더가 없습니다.");
  }

  const challenge = parseChallenge(header);
  const accept = selectAccept(challenge);
  const { header: payment, channelId } = buildPaymentHeader(challenge, accept);

  const retried = await fetch(url, {
    ...init,
    headers: { ...(init.headers as Record<string, string>), "X-PAYMENT": payment },
  });

  const { response, settled } = decodeSettled(retried.headers.get("x-payment-response"));

  return {
    status: retried.status,
    body: await retried.json().catch(() => null),
    authorized: accept.amount,
    settled,
    channelId,
    paymentResponse: response,
  };
}
