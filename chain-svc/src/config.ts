export const PORT = Number(process.env.PORT ?? 8081);

export const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";

export const USDC_MINT = process.env.USDC_MINT ?? "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";

export const AGENT_AUTHORITY_KEYPAIR =
  process.env.AGENT_AUTHORITY_KEYPAIR ?? "/run/secrets/agent-authority.json";
