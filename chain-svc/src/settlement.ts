import anchor from "@coral-xyz/anchor";
import {
  createAssociatedTokenAccountIdempotentInstruction,
  getAssociatedTokenAddressSync,
} from "@solana/spl-token";
import { PublicKey } from "@solana/web3.js";

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

const STATUS_NAMES = ["Funding", "Executing", "Refunding", "Closed"] as const;

export async function campaignStatus(campaignUuid: string): Promise<string> {
  const campaign = await program.account.campaign.fetch(
    campaignPdaFor(uuidToBytes(campaignUuid))
  );
  return STATUS_NAMES.find((name) => name.toLowerCase() in campaign.status) ?? "Unknown";
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
