export const PORT = Number(process.env.PORT ?? 8081);

export const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";

export const USDC_MINT = process.env.USDC_MINT ?? "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";

export const AGENT_AUTHORITY_KEYPAIR =
  process.env.AGENT_AUTHORITY_KEYPAIR ?? "/run/secrets/agent-authority.json";

export const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL ?? "https://chongdae.hajin.xyz";

export const PAY_LABEL = process.env.PAY_LABEL ?? "팬덤 총대 에이전트";

export const PAY_ICON = process.env.PAY_ICON ?? `${PUBLIC_BASE_URL}/static/icon.png`;
