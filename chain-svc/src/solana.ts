import { readFileSync } from "node:fs";

import anchor from "@coral-xyz/anchor";
import { getAssociatedTokenAddressSync } from "@solana/spl-token";
import { Connection, Keypair, PublicKey } from "@solana/web3.js";

import { AGENT_AUTHORITY_KEYPAIR, SOLANA_RPC_URL, USDC_MINT } from "./config.js";
import type { Escrow } from "./idl/escrow.js";

const { AnchorProvider, Program, Wallet } = anchor;

function loadKeypair(path: string): Keypair {
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(readFileSync(path, "utf8"))));
}

const idl = JSON.parse(
  readFileSync(new URL("./idl/escrow.json", import.meta.url), "utf8")
) as Escrow;

export const connection = new Connection(SOLANA_RPC_URL, "confirmed");

export const agentAuthority = loadKeypair(AGENT_AUTHORITY_KEYPAIR);

export const usdcMint = new PublicKey(USDC_MINT);

export const program = new Program<Escrow>(
  idl,
  new AnchorProvider(connection, new Wallet(agentAuthority), { commitment: "confirmed" })
);

export function uuidToBytes(uuid: string): number[] {
  return Array.from(Buffer.from(uuid.replace(/-/g, ""), "hex"));
}

export function campaignPdaFor(uuidBytes: number[]): PublicKey {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("campaign"), Buffer.from(uuidBytes)],
    program.programId
  )[0];
}

export function escrowAtaFor(campaignPda: PublicKey): PublicKey {
  return getAssociatedTokenAddressSync(usdcMint, campaignPda, true);
}

export async function accountExists(address: PublicKey): Promise<boolean> {
  return (await connection.getAccountInfo(address)) !== null;
}
