use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, Token, TokenAccount, Transfer},
};

declare_id!("5QzRtGsFnLRmmMPygmSf5HkLP4cKzNbyMBtM2zx4cS2n");

#[program]
pub mod escrow {
    use super::*;

    pub fn create_campaign(
        ctx: Context<CreateCampaign>,
        uuid: [u8; 16],
        goal_amount: u64,
        deadline: i64,
    ) -> Result<()> {
        require!(goal_amount > 0, EscrowError::InvalidAmount);
        require!(
            deadline > Clock::get()?.unix_timestamp,
            EscrowError::DeadlinePassed
        );

        let campaign = &mut ctx.accounts.campaign;
        campaign.uuid = uuid;
        campaign.authority = ctx.accounts.authority.key();
        campaign.agent_authority = ctx.accounts.agent_authority.key();
        campaign.usdc_mint = ctx.accounts.usdc_mint.key();
        campaign.goal_amount = goal_amount;
        campaign.raised_amount = 0;
        campaign.released_amount = 0;
        campaign.refunded_amount = 0;
        campaign.contributor_count = 0;
        campaign.refunded_count = 0;
        campaign.deadline = deadline;
        campaign.status = CampaignStatus::Funding;
        campaign.bump = ctx.bumps.campaign;
        Ok(())
    }

    pub fn contribute(ctx: Context<Contribute>, amount: u64) -> Result<()> {
        require!(amount > 0, EscrowError::InvalidAmount);
        let campaign = &mut ctx.accounts.campaign;
        require!(
            campaign.status == CampaignStatus::Funding,
            EscrowError::InvalidStatus
        );
        require!(
            Clock::get()?.unix_timestamp <= campaign.deadline,
            EscrowError::DeadlinePassed
        );

        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.contributor_usdc.to_account_info(),
                    to: ctx.accounts.escrow_usdc.to_account_info(),
                    authority: ctx.accounts.contributor.to_account_info(),
                },
            ),
            amount,
        )?;

        let contribution = &mut ctx.accounts.contribution;
        if contribution.amount == 0 {
            contribution.campaign = campaign.key();
            contribution.contributor = ctx.accounts.contributor.key();
            contribution.refunded = false;
            contribution.bump = ctx.bumps.contribution;
            campaign.contributor_count = campaign
                .contributor_count
                .checked_add(1)
                .ok_or(EscrowError::Overflow)?;
        }
        contribution.amount = contribution
            .amount
            .checked_add(amount)
            .ok_or(EscrowError::Overflow)?;
        campaign.raised_amount = campaign
            .raised_amount
            .checked_add(amount)
            .ok_or(EscrowError::Overflow)?;
        Ok(())
    }

    pub fn close_campaign(ctx: Context<CloseCampaign>) -> Result<()> {
        let campaign = &mut ctx.accounts.campaign;
        require!(
            campaign.status == CampaignStatus::Funding,
            EscrowError::InvalidStatus
        );

        campaign.status = if campaign.raised_amount >= campaign.goal_amount {
            CampaignStatus::Executing
        } else if campaign.contributor_count == 0 {
            CampaignStatus::Closed
        } else {
            CampaignStatus::Refunding
        };
        Ok(())
    }

    pub fn release(ctx: Context<Release>, amount: u64) -> Result<()> {
        require!(amount > 0, EscrowError::InvalidAmount);
        let campaign = &ctx.accounts.campaign;
        require!(
            campaign.status == CampaignStatus::Executing,
            EscrowError::InvalidStatus
        );
        let available = campaign
            .raised_amount
            .checked_sub(campaign.released_amount)
            .ok_or(EscrowError::Overflow)?;
        require!(amount <= available, EscrowError::InsufficientFunds);

        let seeds: &[&[u8]] = &[b"campaign", &campaign.uuid, &[campaign.bump]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.escrow_usdc.to_account_info(),
                    to: ctx.accounts.vendor_usdc.to_account_info(),
                    authority: ctx.accounts.campaign.to_account_info(),
                },
                &[seeds],
            ),
            amount,
        )?;

        let campaign = &mut ctx.accounts.campaign;
        campaign.released_amount = campaign
            .released_amount
            .checked_add(amount)
            .ok_or(EscrowError::Overflow)?;
        if campaign.released_amount == campaign.raised_amount {
            campaign.status = CampaignStatus::Closed;
        }
        Ok(())
    }

    pub fn refund(ctx: Context<Refund>) -> Result<()> {
        let campaign = &ctx.accounts.campaign;
        require!(
            campaign.status == CampaignStatus::Refunding,
            EscrowError::InvalidStatus
        );
        let contribution = &ctx.accounts.contribution;
        require!(!contribution.refunded, EscrowError::AlreadyRefunded);
        let amount = contribution.amount;

        let seeds: &[&[u8]] = &[b"campaign", &campaign.uuid, &[campaign.bump]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.escrow_usdc.to_account_info(),
                    to: ctx.accounts.contributor_usdc.to_account_info(),
                    authority: ctx.accounts.campaign.to_account_info(),
                },
                &[seeds],
            ),
            amount,
        )?;

        let contribution = &mut ctx.accounts.contribution;
        contribution.refunded = true;
        let campaign = &mut ctx.accounts.campaign;
        campaign.refunded_amount = campaign
            .refunded_amount
            .checked_add(amount)
            .ok_or(EscrowError::Overflow)?;
        campaign.refunded_count = campaign
            .refunded_count
            .checked_add(1)
            .ok_or(EscrowError::Overflow)?;
        if campaign.refunded_count == campaign.contributor_count {
            campaign.status = CampaignStatus::Closed;
        }
        Ok(())
    }
}


#[derive(Accounts)]
#[instruction(uuid: [u8; 16])]
pub struct CreateCampaign<'info> {
    #[account(
        init,
        payer = agent_authority,
        space = 8 + Campaign::INIT_SPACE,
        seeds = [b"campaign", uuid.as_ref()],
        bump
    )]
    pub campaign: Account<'info, Campaign>,

    #[account(
        init_if_needed,
        payer = agent_authority,
        associated_token::mint = usdc_mint,
        associated_token::authority = campaign,
    )]
    pub escrow_usdc: Account<'info, TokenAccount>,

    /// CHECK:
    pub authority: UncheckedAccount<'info>,

    #[account(mut)]
    pub agent_authority: Signer<'info>,

    pub usdc_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Contribute<'info> {
    #[account(
        mut,
        seeds = [b"campaign", campaign.uuid.as_ref()],
        bump = campaign.bump
    )]
    pub campaign: Account<'info, Campaign>,

    #[account(
        init_if_needed,
        payer = agent_authority,
        space = 8 + Contribution::INIT_SPACE,
        seeds = [b"contribution", campaign.key().as_ref(), contributor.key().as_ref()],
        bump
    )]
    pub contribution: Account<'info, Contribution>,

    pub contributor: Signer<'info>,

    #[account(mut)]
    pub agent_authority: Signer<'info>,

    #[account(
        mut,
        associated_token::mint = campaign.usdc_mint,
        associated_token::authority = contributor,
    )]
    pub contributor_usdc: Account<'info, TokenAccount>,

    #[account(
        mut,
        associated_token::mint = campaign.usdc_mint,
        associated_token::authority = campaign,
    )]
    pub escrow_usdc: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct CloseCampaign<'info> {
    #[account(
        mut,
        seeds = [b"campaign", campaign.uuid.as_ref()],
        bump = campaign.bump,
        has_one = agent_authority @ EscrowError::Unauthorized
    )]
    pub campaign: Account<'info, Campaign>,
    pub agent_authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct Release<'info> {
    #[account(
        mut,
        seeds = [b"campaign", campaign.uuid.as_ref()],
        bump = campaign.bump,
        has_one = agent_authority @ EscrowError::Unauthorized
    )]
    pub campaign: Account<'info, Campaign>,

    pub agent_authority: Signer<'info>,

    #[account(
        mut,
        associated_token::mint = campaign.usdc_mint,
        associated_token::authority = campaign,
    )]
    pub escrow_usdc: Account<'info, TokenAccount>,

    #[account(mut, token::mint = campaign.usdc_mint)]
    pub vendor_usdc: Account<'info, TokenAccount>,

    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Refund<'info> {
    #[account(
        mut,
        seeds = [b"campaign", campaign.uuid.as_ref()],
        bump = campaign.bump,
        has_one = agent_authority @ EscrowError::Unauthorized
    )]
    pub campaign: Account<'info, Campaign>,

    #[account(
        mut,
        seeds = [b"contribution", campaign.key().as_ref(), contribution.contributor.as_ref()],
        bump = contribution.bump,
        constraint = contribution.campaign == campaign.key() @ EscrowError::Unauthorized
    )]
    pub contribution: Account<'info, Contribution>,

    #[account(mut)]
    pub agent_authority: Signer<'info>,

    #[account(
        mut,
        associated_token::mint = campaign.usdc_mint,
        associated_token::authority = campaign,
    )]
    pub escrow_usdc: Account<'info, TokenAccount>,

    #[account(
        init_if_needed,
        payer = agent_authority,
        associated_token::mint = usdc_mint,
        associated_token::authority = contributor_wallet,
    )]
    pub contributor_usdc: Account<'info, TokenAccount>,

    /// CHECK:
    #[account(address = contribution.contributor @ EscrowError::Unauthorized)]
    pub contributor_wallet: UncheckedAccount<'info>,

    #[account(address = campaign.usdc_mint)]
    pub usdc_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}


#[account]
#[derive(InitSpace)]
pub struct Campaign {
    pub uuid: [u8; 16],
    pub authority: Pubkey,
    pub agent_authority: Pubkey,
    pub usdc_mint: Pubkey,
    pub goal_amount: u64,
    pub raised_amount: u64,
    pub released_amount: u64,
    pub refunded_amount: u64,
    pub contributor_count: u32,
    pub refunded_count: u32,
    pub deadline: i64,
    pub status: CampaignStatus,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Contribution {
    pub campaign: Pubkey,
    pub contributor: Pubkey,
    pub amount: u64,
    pub refunded: bool,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum CampaignStatus {
    Funding,
    Executing,
    Refunding,
    Closed,
}

#[error_code]
pub enum EscrowError {
    #[msg("금액이 유효하지 않습니다")]
    InvalidAmount,
    #[msg("마감이 지났습니다")]
    DeadlinePassed,
    #[msg("현재 상태에서 허용되지 않는 동작입니다")]
    InvalidStatus,
    #[msg("권한이 없습니다")]
    Unauthorized,
    #[msg("escrow 잔액이 부족합니다")]
    InsufficientFunds,
    #[msg("이미 환불되었습니다")]
    AlreadyRefunded,
    #[msg("산술 오버플로")]
    Overflow,
}
