import anchor from "@coral-xyz/anchor";
import { encodeURL } from "@solana/pay";
import { getAssociatedTokenAddressSync } from "@solana/spl-token";
import { Keypair, PublicKey, Transaction } from "@solana/web3.js";

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

export async function findReferenceSignature(reference: string): Promise<string | null> {
  const signatures = await connection.getSignaturesForAddress(
    new PublicKey(reference),
    { limit: 10 },
    "confirmed"
  );
  return signatures.find((s) => s.err === null)?.signature ?? null;
}
