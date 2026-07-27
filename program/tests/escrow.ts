import * as anchor from "@coral-xyz/anchor";
import { Program, BN } from "@coral-xyz/anchor";
import {
  createMint,
  getOrCreateAssociatedTokenAccount,
  mintTo,
  getAssociatedTokenAddressSync,
  getAccount,
} from "@solana/spl-token";
import { Keypair, PublicKey, SystemProgram } from "@solana/web3.js";
import { assert } from "chai";
import { Escrow } from "../target/types/escrow";

describe("escrow", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.Escrow as Program<Escrow>;

  const agent = provider.wallet as anchor.Wallet;
  const chongdae = Keypair.generate();
  const fan = Keypair.generate();
  const fan2 = Keypair.generate();
  const vendor = Keypair.generate();

  let usdcMint: PublicKey;
  let fanUsdc: PublicKey;
  let fan2Usdc: PublicKey;

  const uuid = Array.from(crypto.getRandomValues(new Uint8Array(16)));
  const GOAL = new BN(30_000_000_000);
  const CONTRIBUTION = new BN(30_000_000);

  const [campaignPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("campaign"), Buffer.from(uuid)],
    program.programId
  );

  before(async () => {
    try {
      await provider.connection.requestAirdrop(fan.publicKey, 1_000_000_000);
    } catch {}

    usdcMint = await createMint(
      provider.connection,
      agent.payer,
      agent.publicKey,
      null,
      6
    );
    const fanAta = await getOrCreateAssociatedTokenAccount(
      provider.connection,
      agent.payer,
      usdcMint,
      fan.publicKey
    );
    fanUsdc = fanAta.address;
    await mintTo(
      provider.connection,
      agent.payer,
      usdcMint,
      fanUsdc,
      agent.payer,
      100_000_000_000
    );

    const fan2Ata = await getOrCreateAssociatedTokenAccount(
      provider.connection,
      agent.payer,
      usdcMint,
      fan2.publicKey
    );
    fan2Usdc = fan2Ata.address;
    await mintTo(
      provider.connection,
      agent.payer,
      usdcMint,
      fan2Usdc,
      agent.payer,
      100_000_000_000
    );
  });

  it("create_campaign: PDA + escrow ATA 생성", async () => {
    const deadline = new BN(Math.floor(Date.now() / 1000) + 3600);
    await program.methods
      .createCampaign(uuid, GOAL, deadline)
      .accounts({
        authority: chongdae.publicKey,
        agentAuthority: agent.publicKey,
        usdcMint,
      })
      .rpc();

    const campaign = await program.account.campaign.fetch(campaignPda);
    assert.ok(campaign.goalAmount.eq(GOAL));
    assert.equal(campaign.contributorCount, 0);
    assert.deepEqual(campaign.status, { funding: {} });
  });

  it("contribute: 기여 + 반복 기여 누적 (D11-4)", async () => {
    const escrowUsdc = getAssociatedTokenAddressSync(usdcMint, campaignPda, true);

    for (let i = 0; i < 2; i++) {
      await program.methods
        .contribute(CONTRIBUTION)
        .accounts({
          campaign: campaignPda,
          contributor: fan.publicKey,
          agentAuthority: agent.publicKey,
          contributorUsdc: fanUsdc,
          escrowUsdc,
        })
        .signers([fan])
        .rpc();
    }
    await program.methods
      .contribute(CONTRIBUTION)
      .accounts({
        campaign: campaignPda,
        contributor: fan2.publicKey,
        agentAuthority: agent.publicKey,
        contributorUsdc: fan2Usdc,
        escrowUsdc,
      })
      .signers([fan2])
      .rpc();

    const campaign = await program.account.campaign.fetch(campaignPda);
    assert.ok(campaign.raisedAmount.eq(CONTRIBUTION.muln(3)));
    assert.equal(campaign.contributorCount, 2);

    const escrowBal = await getAccount(provider.connection, escrowUsdc);
    assert.equal(escrowBal.amount, BigInt(CONTRIBUTION.muln(3).toString()));
  });

  it("close_campaign: 목표 미달 → Refunding 전이 (agent_authority 서명)", async () => {
    await program.methods
      .closeCampaign()
      .accounts({ campaign: campaignPda, agentAuthority: agent.publicKey })
      .rpc();

    const campaign = await program.account.campaign.fetch(campaignPda);
    assert.deepEqual(campaign.status, { refunding: {} });
  });

  it("close_campaign: 총대 지갑 서명으로는 불가 (gasless 설계와 정합)", async () => {
    const uuid2 = Array.from(crypto.getRandomValues(new Uint8Array(16)));
    const [pda2] = PublicKey.findProgramAddressSync(
      [Buffer.from("campaign"), Buffer.from(uuid2)],
      program.programId
    );
    const deadline = new BN(Math.floor(Date.now() / 1000) + 3600);
    await program.methods
      .createCampaign(uuid2, GOAL, deadline)
      .accounts({
        authority: chongdae.publicKey,
        agentAuthority: agent.publicKey,
        usdcMint,
      })
      .rpc();

    try {
      await program.methods
        .closeCampaign()
        .accounts({ campaign: pda2, agentAuthority: chongdae.publicKey })
        .signers([chongdae])
        .rpc();
      assert.fail("총대 서명의 close가 통과되면 안 된다");
    } catch (e: any) {
      assert.include(e.toString(), "Unauthorized");
    }
  });

  it("성공 경로: 목표 달성 → Executing → 전액 집행 → Closed", async () => {
    const uuid3 = Array.from(crypto.getRandomValues(new Uint8Array(16)));
    const [pda3] = PublicKey.findProgramAddressSync(
      [Buffer.from("campaign"), Buffer.from(uuid3)],
      program.programId
    );
    const smallGoal = new BN(50_000_000);
    const deadline = new BN(Math.floor(Date.now() / 1000) + 3600);
    await program.methods
      .createCampaign(uuid3, smallGoal, deadline)
      .accounts({
        authority: chongdae.publicKey,
        agentAuthority: agent.publicKey,
        usdcMint,
      })
      .rpc();

    const escrowUsdc3 = getAssociatedTokenAddressSync(usdcMint, pda3, true);
    const raised = new BN(60_000_000);
    await program.methods
      .contribute(raised)
      .accounts({
        campaign: pda3,
        contributor: fan.publicKey,
        agentAuthority: agent.publicKey,
        contributorUsdc: fanUsdc,
        escrowUsdc: escrowUsdc3,
      })
      .signers([fan])
      .rpc();

    await program.methods
      .closeCampaign()
      .accounts({ campaign: pda3, agentAuthority: agent.publicKey })
      .rpc();
    let campaign = await program.account.campaign.fetch(pda3);
    assert.deepEqual(campaign.status, { executing: {} });

    const vendorAta = await getOrCreateAssociatedTokenAccount(
      provider.connection,
      agent.payer,
      usdcMint,
      vendor.publicKey
    );
    await program.methods
      .release(raised)
      .accounts({
        campaign: pda3,
        agentAuthority: agent.publicKey,
        escrowUsdc: escrowUsdc3,
        vendorUsdc: vendorAta.address,
      })
      .rpc();

    campaign = await program.account.campaign.fetch(pda3);
    assert.deepEqual(campaign.status, { closed: {} });
    assert.ok(campaign.releasedAmount.eq(raised));

    const vendorBal = await getAccount(provider.connection, vendorAta.address);
    assert.equal(vendorBal.amount, BigInt(raised.toString()));
  });

  it("기여자 0명 캠페인 마감 → 즉시 Closed (Refunding 영구 정지 방지)", async () => {
    const uuid4 = Array.from(crypto.getRandomValues(new Uint8Array(16)));
    const [pda4] = PublicKey.findProgramAddressSync(
      [Buffer.from("campaign"), Buffer.from(uuid4)],
      program.programId
    );
    const deadline = new BN(Math.floor(Date.now() / 1000) + 3600);
    await program.methods
      .createCampaign(uuid4, GOAL, deadline)
      .accounts({
        authority: chongdae.publicKey,
        agentAuthority: agent.publicKey,
        usdcMint,
      })
      .rpc();

    await program.methods
      .closeCampaign()
      .accounts({ campaign: pda4, agentAuthority: agent.publicKey })
      .rpc();

    const campaign = await program.account.campaign.fetch(pda4);
    assert.deepEqual(campaign.status, { closed: {} });
  });

  it("refund: 부분 환불 + refunded 플래그로 이중 환불 차단 (P4)", async () => {
    const escrowUsdc = getAssociatedTokenAddressSync(usdcMint, campaignPda, true);
    const [contribution1] = PublicKey.findProgramAddressSync(
      [
        Buffer.from("contribution"),
        campaignPda.toBuffer(),
        fan.publicKey.toBuffer(),
      ],
      program.programId
    );

    await program.methods
      .refund()
      .accounts({
        campaign: campaignPda,
        contribution: contribution1,
        agentAuthority: agent.publicKey,
        escrowUsdc,
        contributorUsdc: fanUsdc,
        contributorWallet: fan.publicKey,
        usdcMint,
      })
      .rpc();

    let campaign = await program.account.campaign.fetch(campaignPda);
    assert.ok(campaign.refundedAmount.eq(CONTRIBUTION.muln(2)));
    assert.deepEqual(campaign.status, { refunding: {} });

    try {
      await program.methods
        .refund()
        .accounts({
          campaign: campaignPda,
          contribution: contribution1,
          agentAuthority: agent.publicKey,
          escrowUsdc,
          contributorUsdc: fanUsdc,
          contributorWallet: fan.publicKey,
          usdcMint,
        })
        .rpc();
      assert.fail("이중 환불이 통과되면 안 된다");
    } catch (e: any) {
      assert.include(e.toString(), "AlreadyRefunded");
    }

    const [contribution2] = PublicKey.findProgramAddressSync(
      [
        Buffer.from("contribution"),
        campaignPda.toBuffer(),
        fan2.publicKey.toBuffer(),
      ],
      program.programId
    );
    await program.methods
      .refund()
      .accounts({
        campaign: campaignPda,
        contribution: contribution2,
        agentAuthority: agent.publicKey,
        escrowUsdc,
        contributorUsdc: fan2Usdc,
        contributorWallet: fan2.publicKey,
        usdcMint,
      })
      .rpc();

    campaign = await program.account.campaign.fetch(campaignPda);
    assert.ok(campaign.refundedAmount.eq(CONTRIBUTION.muln(3)));
    assert.deepEqual(campaign.status, { closed: {} });
  });

  it("release: 총대 서명으로는 불가 (D2 — 집행 버튼 제거)", async () => {
    const escrowUsdc = getAssociatedTokenAddressSync(usdcMint, campaignPda, true);
    const vendorAta = await getOrCreateAssociatedTokenAccount(
      provider.connection,
      agent.payer,
      usdcMint,
      vendor.publicKey
    );

    try {
      await program.methods
        .release(new BN(1_000_000))
        .accounts({
          campaign: campaignPda,
          agentAuthority: chongdae.publicKey,
          escrowUsdc,
          vendorUsdc: vendorAta.address,
        })
        .signers([chongdae])
        .rpc();
      assert.fail("총대의 release가 통과되면 안 된다");
    } catch (e: any) {
      assert.include(e.toString(), "Unauthorized");
    }
  });
});
