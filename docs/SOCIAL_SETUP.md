# Social Logins Setup

All social logins live in Connections → Provider Logins — same card pattern
as OAuth: paste the client ID, see the setup cost up front, then Device or
Browser login. Secrets follow the same vault rules (write-only, 600 perms,
never displayed).

## Zero-registration (no provider signup at all)

- **Mastodon**: set your instance if it isn't mastodon.social
  (`MASTODON_INSTANCE=fosstodon.org`), create any app in that instance's
  Settings → Development, paste the client ID. Standard OAuth + PKCE.
- **Bluesky**: no OAuth app needed. Save an app password in Stored Keys
  (Bluesky Settings → App passwords; label it with your handle), then use
  the Bluesky section to post or read your timeline. Sessions live only
  inside each request — re-login is automatic per action. Public profile
  reads need no auth at all.

## One-time-free registration

- **Reddit**: reddit.com/prefs/apps → create a *script* app (personal use)
  or *web* app → paste ID + secret. Ghost authenticates the token call
  with HTTP Basic automatically (`duration=permanent`, account holds one
  token). Start with `identity history read` scopes.
- **Discord**: discord.com/developers → New Application → OAuth2 → paste
  the client ID (`identify guilds` scopes). Automating *user* accounts
  (self-bots) is banned by Discord — use this login for identity/guild
  reads, and paste a **bot token** in Stored Keys for any automation.
- **TikTok**: Login Kit app (self-serve) → `user.info.basic` works
  immediately. Content posting needs TikTok audit approval — Ghost does
  not expose publishing until that clears.
- **Facebook**: free Meta app → basic login works. Deeper permissions
  (pages, messaging) need Meta App Review; the card tells you which.
- **Instagram**: Business or Creator account **plus** a linked Facebook
  Page are hard requirements from Meta. Own-account Standard Access needs
  no review; anything third-party needs full review.

## Login-only: X

`Login with X` works (OAuth 2.0 + PKCE, `tweet.read users.read
offline.access`), but X bills **every API call** pay-per-use with no free
read tier. So Ghost stores the X token and **refuses all X API calls**
with a `login-only` error until you explicitly approve spending. Unlocking
it later means: your decision, a spend cap, and a separate change — it can
never happen silently.

## Banned by policy (Ghost will not do these)

- **LinkedIn automation** (credential use, bots, scraping): permanent
  account-closure risk. Sign-in only.
- **Discord self-bots**: banned. Bot tokens only.
- **X scraping workarounds**: ToS gray area. Official API or nothing.
