import { getAssociatedTokenAddressSync } from "@solana/spl-token";
import {
  PublicKey,
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
  Transaction,
  TransactionInstruction,
} from "@solana/web3.js";
import type { Keypair } from "@solana/web3.js";

export const PAYMENT_CHANNELS_PROGRAM = new PublicKey(
  "CHNLxYvVA28MJP9PrFuDXccuoGXAx7jBacfLEkahyGsX"
);

const ASSOCIATED_TOKEN_PROGRAM = new PublicKey(
  "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
);

const OPEN_DISCRIMINATOR = 1;

export interface Recipient {
  recipient: PublicKey;
  bps: number;
}

export interface OpenChannelParams {
  payer: PublicKey;
  feePayer: PublicKey;
  mint: PublicKey;
  authorizedSigner: PublicKey;
  tokenProgram: PublicKey;
  recipients: Recipient[];
  salt: bigint;
  deposit: bigint;
  gracePeriod: number;
  openSlot: bigint;
}

function u64(value: bigint): Buffer {
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64LE(value);
  return buffer;
}

export function channelPda(params: OpenChannelParams): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [
      Buffer.from("channel"),
      params.payer.toBuffer(),
      params.feePayer.toBuffer(),
      params.mint.toBuffer(),
      params.authorizedSigner.toBuffer(),
      u64(params.salt),
      u64(params.openSlot),
    ],
    PAYMENT_CHANNELS_PROGRAM
  );
}

export function eventAuthorityPda(): PublicKey {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("event_authority")],
    PAYMENT_CHANNELS_PROGRAM
  )[0];
}

function encodeOpenArgs(params: OpenChannelParams): Buffer {
  const head = Buffer.alloc(33);
  head.writeUInt8(OPEN_DISCRIMINATOR, 0);
  head.writeBigUInt64LE(params.salt, 1);
  head.writeBigUInt64LE(params.deposit, 9);
  head.writeUInt32LE(params.gracePeriod, 17);
  head.writeBigUInt64LE(params.openSlot, 21);
  head.writeUInt32LE(params.recipients.length, 29);

  const entries = params.recipients.map(({ recipient, bps }) => {
    const entry = Buffer.alloc(34);
    recipient.toBuffer().copy(entry, 0);
    entry.writeUInt16LE(bps, 32);
    return entry;
  });

  return Buffer.concat([head, ...entries]);
}

export function buildOpenInstruction(params: OpenChannelParams): TransactionInstruction {
  const [channel] = channelPda(params);
  const payerTokenAccount = getAssociatedTokenAddressSync(
    params.mint,
    params.payer,
    false,
    params.tokenProgram
  );
  const channelTokenAccount = getAssociatedTokenAddressSync(
    params.mint,
    channel,
    true,
    params.tokenProgram
  );

  return new TransactionInstruction({
    programId: PAYMENT_CHANNELS_PROGRAM,
    data: encodeOpenArgs(params),
    keys: [
      { pubkey: params.payer, isSigner: true, isWritable: true },
      { pubkey: params.feePayer, isSigner: true, isWritable: true },
      { pubkey: params.feePayer, isSigner: false, isWritable: false },
      { pubkey: params.mint, isSigner: false, isWritable: false },
      { pubkey: params.authorizedSigner, isSigner: false, isWritable: false },
      { pubkey: channel, isSigner: false, isWritable: true },
      { pubkey: payerTokenAccount, isSigner: false, isWritable: true },
      { pubkey: channelTokenAccount, isSigner: false, isWritable: true },
      { pubkey: params.tokenProgram, isSigner: false, isWritable: false },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      { pubkey: SYSVAR_RENT_PUBKEY, isSigner: false, isWritable: false },
      { pubkey: ASSOCIATED_TOKEN_PROGRAM, isSigner: false, isWritable: false },
      { pubkey: eventAuthorityPda(), isSigner: false, isWritable: false },
      { pubkey: PAYMENT_CHANNELS_PROGRAM, isSigner: false, isWritable: false },
    ],
  });
}

export function buildSignedOpenTransaction(
  params: OpenChannelParams,
  blockhash: string,
  payerKeypair: Keypair
): string {
  const transaction = new Transaction({
    feePayer: params.feePayer,
    blockhash,
    lastValidBlockHeight: 0,
  }).add(buildOpenInstruction(params));

  transaction.partialSign(payerKeypair);

  return transaction.serialize({ requireAllSignatures: false }).toString("base64");
}
