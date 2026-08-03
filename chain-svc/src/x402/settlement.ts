import { Connection, PublicKey } from "@solana/web3.js";
import type { TokenBalance } from "@solana/web3.js";

import { X402_MAINNET_RPC_URL } from "../config.js";
import { payerKeypair } from "./client.js";

export interface ChannelSettlement {
  settled: string | null;
  openTx: string | null;
  closeTx: string | null;
}

let mainnetConnection: Connection | null = null;

function mainnet(): Connection {
  if (!mainnetConnection) {
    mainnetConnection = new Connection(X402_MAINNET_RPC_URL, "confirmed");
  }
  return mainnetConnection;
}

function balanceOf(entries: TokenBalance[] | null | undefined, owner: string): bigint {
  const found = (entries ?? []).find((entry) => entry.owner === owner);
  return BigInt(found?.uiTokenAmount.amount ?? "0");
}

export async function resolveSettlement(channelId: string): Promise<ChannelSettlement> {
  const channel = new PublicKey(channelId);
  const signatures = await mainnet().getSignaturesForAddress(channel, { limit: 20 });
  if (signatures.length === 0) {
    return { settled: null, openTx: null, closeTx: null };
  }

  const ordered = [...signatures].reverse();
  const openTx = ordered[0].signature;
  const payer = payerKeypair().publicKey.toBase58();

  for (const entry of ordered) {
    if (entry.err) continue;

    const transaction = await mainnet().getParsedTransaction(entry.signature, {
      maxSupportedTransactionVersion: 0,
    });
    const meta = transaction?.meta;
    if (!meta) continue;

    const deposit = balanceOf(meta.preTokenBalances, channelId);
    const remaining = balanceOf(meta.postTokenBalances, channelId);
    if (deposit === 0n || remaining !== 0n) continue;

    const refund =
      balanceOf(meta.postTokenBalances, payer) - balanceOf(meta.preTokenBalances, payer);
    const settled = deposit - (refund > 0n ? refund : 0n);

    return {
      settled: (settled > 0n ? settled : 0n).toString(),
      openTx,
      closeTx: entry.signature,
    };
  }

  return { settled: null, openTx, closeTx: null };
}
