import {
  createAssociatedTokenAccountIdempotentInstruction,
  createTransferInstruction,
  getAccount,
  getAssociatedTokenAddressSync,
} from "@solana/spl-token";
import { PublicKey, Transaction } from "@solana/web3.js";

import { PAYSH_TREASURY } from "./config.js";
import { agentAuthority, connection, provider, usdcMint } from "./solana.js";

export interface MicropayResult {
  paid: boolean;
  signature: string | null;
  reason: string | null;
}

export async function micropay(amount: bigint): Promise<MicropayResult> {
  if (!PAYSH_TREASURY) {
    return { paid: false, signature: null, reason: "treasury_not_configured" };
  }
  const treasury = new PublicKey(PAYSH_TREASURY);
  const source = getAssociatedTokenAddressSync(usdcMint, agentAuthority.publicKey);
  const destination = getAssociatedTokenAddressSync(usdcMint, treasury);

  let balance = 0n;
  try {
    balance = (await getAccount(connection, source)).amount;
  } catch {
    return { paid: false, signature: null, reason: "insufficient_funds" };
  }
  if (balance < amount) {
    return { paid: false, signature: null, reason: "insufficient_funds" };
  }

  const transaction = new Transaction().add(
    createAssociatedTokenAccountIdempotentInstruction(
      agentAuthority.publicKey,
      destination,
      treasury,
      usdcMint
    ),
    createTransferInstruction(source, destination, agentAuthority.publicKey, amount)
  );
  const signature = await provider.sendAndConfirm(transaction);
  return { paid: true, signature, reason: null };
}
