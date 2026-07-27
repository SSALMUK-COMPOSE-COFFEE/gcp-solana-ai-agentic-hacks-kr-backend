import anchor from "@coral-xyz/anchor";
import {
  createAssociatedTokenAccountIdempotentInstruction,
  getAssociatedTokenAddressSync,
} from "@solana/spl-token";
import { PublicKey, Transaction } from "@solana/web3.js";

import {
  agentAuthority,
  campaignPdaFor,
  connection,
  escrowAtaFor,
  program,
  provider,
  usdcMint,
  uuidToBytes,
} from "./solana.js";

const { BN } = anchor;

const STATUS_NAMES = ["Funding", "Executing", "Refunding", "Closed"] as const;

const REFUND_BATCH_SIZE = 5;

function statusName(status: object): string {
  return STATUS_NAMES.find((name) => name.toLowerCase() in status) ?? "Unknown";
}

export async function campaignStatus(campaignUuid: string): Promise<string> {
  const campaign = await program.account.campaign.fetch(
    campaignPdaFor(uuidToBytes(campaignUuid))
  );
  return statusName(campaign.status);
}

export async function closeCampaign(campaignUuid: string): Promise<string> {
  const campaignPda = campaignPdaFor(uuidToBytes(campaignUuid));

  return program.methods
    .closeCampaign()
    .accountsPartial({
      campaign: campaignPda,
      agentAuthority: agentAuthority.publicKey,
    })
    .rpc();
}

export async function release(
  campaignUuid: string,
  vendorWallet: string,
  amount: bigint
): Promise<string> {
  const campaignPda = campaignPdaFor(uuidToBytes(campaignUuid));
  const vendor = new PublicKey(vendorWallet);
  const vendorUsdc = getAssociatedTokenAddressSync(usdcMint, vendor);

  const preInstructions =
    (await connection.getAccountInfo(vendorUsdc)) === null
      ? [
          createAssociatedTokenAccountIdempotentInstruction(
            agentAuthority.publicKey,
            vendorUsdc,
            vendor,
            usdcMint
          ),
        ]
      : [];

  return program.methods
    .release(new BN(amount.toString()))
    .accountsPartial({
      campaign: campaignPda,
      agentAuthority: agentAuthority.publicKey,
      escrowUsdc: escrowAtaFor(campaignPda),
      vendorUsdc,
    })
    .preInstructions(preInstructions)
    .rpc();
}

export interface RefundBatchResult {
  refundedCount: number;
  refundedAmount: string;
  pendingCount: number;
  signatures: string[];
  status: string;
}

export async function refundBatch(campaignUuid: string): Promise<RefundBatchResult> {
  const campaignPda = campaignPdaFor(uuidToBytes(campaignUuid));
  const escrowUsdc = escrowAtaFor(campaignPda);

  const contributions = await program.account.contribution.all([
    { memcmp: { offset: 8, bytes: campaignPda.toBase58() } },
  ]);
  const pending = contributions.filter(
    ({ account }) => !account.refunded && account.amount.gt(new BN(0))
  );

  const signatures: string[] = [];
  let refundedNow = 0;
  for (let offset = 0; offset < pending.length; offset += REFUND_BATCH_SIZE) {
    const batch = pending.slice(offset, offset + REFUND_BATCH_SIZE);
    const transaction = new Transaction();
    for (const { publicKey, account } of batch) {
      transaction.add(
        await program.methods
          .refund()
          .accountsPartial({
            campaign: campaignPda,
            contribution: publicKey,
            agentAuthority: agentAuthority.publicKey,
            escrowUsdc,
            contributorUsdc: getAssociatedTokenAddressSync(usdcMint, account.contributor),
            contributorWallet: account.contributor,
            usdcMint,
          })
          .instruction()
      );
    }
    try {
      signatures.push(await provider.sendAndConfirm(transaction));
      refundedNow += batch.length;
    } catch (err) {
      console.error(`refund batch failed at offset ${offset}:`, err);
      break;
    }
  }

  const campaign = await program.account.campaign.fetch(campaignPda);
  return {
    refundedCount: campaign.refundedCount,
    refundedAmount: campaign.refundedAmount.toString(),
    pendingCount: pending.length - refundedNow,
    signatures,
    status: statusName(campaign.status),
  };
}
