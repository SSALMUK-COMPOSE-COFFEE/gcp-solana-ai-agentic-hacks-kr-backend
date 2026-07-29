export const PORT = Number(process.env.PORT ?? 8081);

export const SOLANA_RPC_URL = process.env.SOLANA_RPC_URL ?? "https://api.devnet.solana.com";

export const USDC_MINT = process.env.USDC_MINT ?? "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";

export const AGENT_AUTHORITY_KEYPAIR =
  process.env.AGENT_AUTHORITY_KEYPAIR ?? "/run/secrets/agent-authority.json";

export const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL ?? "https://chongdae.hajin.xyz";

export const PAY_LABEL = process.env.PAY_LABEL ?? "팬덤 총대 에이전트";

export const PAYSH_TREASURY = process.env.PAYSH_TREASURY ?? "";

export const PAY_ICON = process.env.PAY_ICON ?? `${PUBLIC_BASE_URL}/static/icon.png`;

export const AI_RAIL = process.env.AI_RAIL ?? "direct";

export const X402_MAINNET_RPC_URL =
  process.env.X402_MAINNET_RPC_URL ?? "https://api.mainnet-beta.solana.com";

export const X402_KEYPAIR = process.env.X402_KEYPAIR ?? "/run/secrets/agent-mainnet.json";

export const X402_ASSET =
  process.env.X402_ASSET ?? "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

export const GEMINI_GATEWAY_URL =
  process.env.GEMINI_GATEWAY_URL ?? "https://generativelanguage.google.gateway-402.com";
