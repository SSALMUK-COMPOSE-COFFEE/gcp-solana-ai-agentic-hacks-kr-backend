import anchor from "@coral-xyz/anchor";
import { encodeURL } from "@solana/pay";
import { getAssociatedTokenAddressSync } from "@solana/spl-token";
import { Keypair, PublicKey, Transaction } from "@solana/web3.js";
import type { ParsedTransactionWithMeta, TokenBalance } from "@solana/web3.js";

import { PUBLIC_BASE_URL } from "./config.js";
import {
  agentAuthority,
  campaignPdaFor,
  connection,
  escrowAtaFor,
  program,
  usdcMint,
  uuidToBytes,
} from "./solana.js";

const { BN } = anchor;

export function newReference(): string {
  return Keypair.generate().publicKey.toBase58();
}

export function paymentUrl(reference: string): string {
  const link = new URL(`${PUBLIC_BASE_URL}/payment/solana-pay/tx`);
  link.searchParams.set("ref", reference);
  return encodeURL({ link }).toString();
}

export async function buildContributeTransaction(
  campaignUuid: string,
  amount: bigint,
  reference: string,
  account: string
): Promise<string> {
  const campaignPda = campaignPdaFor(uuidToBytes(campaignUuid));
  const contributor = new PublicKey(account);

  const instruction = await program.methods
    .contribute(new BN(amount.toString()))
    .accountsPartial({
      campaign: campaignPda,
      contributor,
      agentAuthority: agentAuthority.publicKey,
      contributorUsdc: getAssociatedTokenAddressSync(usdcMint, contributor),
      escrowUsdc: escrowAtaFor(campaignPda),
    })
    .instruction();

  instruction.keys.push({
    pubkey: new PublicKey(reference),
    isSigner: false,
    isWritable: false,
  });

  const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash();
  const transaction = new Transaction({
    feePayer: agentAuthority.publicKey,
    blockhash,
    lastValidBlockHeight,
  }).add(instruction);

  transaction.partialSign(agentAuthority);

  return transaction.serialize({ requireAllSignatures: false }).toString("base64");
}

export interface ReferenceCheck {
  txSignature: string | null;
  reason: string | null;
}

function escrowDelta(tx: ParsedTransactionWithMeta, escrowUsdc: string): bigint {
  const keys = tx.transaction.message.accountKeys;
  const mint = usdcMint.toBase58();
  const pick = (balances: TokenBalance[] | null | undefined) =>
    balances?.find(
      (balance) =>
        balance.mint === mint &&
        keys[balance.accountIndex]?.pubkey.toBase58() === escrowUsdc
    );

  const before = BigInt(pick(tx.meta?.preTokenBalances)?.uiTokenAmount.amount ?? "0");
  const after = BigInt(pick(tx.meta?.postTokenBalances)?.uiTokenAmount.amount ?? "0");
  return after - before;
}

function callsEscrowProgram(tx: ParsedTransactionWithMeta): boolean {
  const escrowProgram = program.programId.toBase58();
  const outer = tx.transaction.message.instructions;
  const inner = tx.meta?.innerInstructions?.flatMap((entry) => entry.instructions) ?? [];
  return [...outer, ...inner].some(
    (instruction) => instruction.programId.toBase58() === escrowProgram
  );
}

export async function findReferenceSignature(
  reference: string,
  campaignUuid: string,
  amount: bigint
): Promise<ReferenceCheck> {
  const signatures = await connection.getSignaturesForAddress(
    new PublicKey(reference),
    { limit: 10 },
    "confirmed"
  );

  const escrowUsdc = escrowAtaFor(campaignPdaFor(uuidToBytes(campaignUuid))).toBase58();
  let reason: string | null = null;

  for (const { signature, err } of signatures) {
    if (err !== null) continue;

    const tx = await connection.getParsedTransaction(signature, {
      commitment: "confirmed",
      maxSupportedTransactionVersion: 0,
    });
    if (!tx || tx.meta?.err) continue;

    if (!callsEscrowProgram(tx)) {
      reason = `escrow 프로그램을 호출하지 않은 트랜잭션입니다 (${signature})`;
      continue;
    }

    const delta = escrowDelta(tx, escrowUsdc);
    if (delta >= amount) {
      return { txSignature: signature, reason: null };
    }
    reason = `escrow 입금액 ${delta}이 기대 금액 ${amount}에 미치지 않습니다 (${signature})`;
  }

  return { txSignature: null, reason };
}
