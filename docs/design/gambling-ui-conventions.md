# Gambling UI conventions: research for the Keno product and back office

**Status:** Part A research, for operator review. No code depends on it yet.
**Written:** 2026-09-26.
**Drives:** Part B (design system), Part C (Keno player UI), Part D (admin
portal), Part E (game abstraction, seamless wallet, sports sketch).

## How this was researched, and its limits

This cloud environment's network policy only allows package registries.
Every operator, regulator and Telegram documentation site I tried to open
(`core.telegram.org`, `gamblingcommission.gov.uk`,
`docs.telegram-mini-apps.com`) was refused by the egress proxy. So the
evidence comes from three places:

1. **Web search result excerpts.** Search worked. Opening pages didn't.
   Everything cited below from a website is what the search engine's excerpt
   of that page said, not a full reading of it. Where that matters (exact
   regulatory wording, for instance), the text says so. Before any of it is
   treated as a compliance statement, someone with open network access should
   read the primary page.
2. **One primary source I could actually open:** the Telegram WebApp type
   definitions published on npm as `@twa-dev/types` 8.0.2. These are the
   real field and method names, so the Telegram section is on firmer ground
   than the rest.
3. **This repository:** what the Keno engine, Mini App and admin panel already
   do (`docs/keno/*`, `web/miniapp/js/keno.js`, `web/admin/js/screens/*`), so
   each convention ends with where we already are and what's missing.

I've kept a claim only where a source supports it. Where I'm reasoning
rather than reporting, the text says "recommendation".

---

## 1. What players expect from a real-money game product

### 1.1 The frame around every game

Across sportsbooks and casino lobbies the same frame keeps recurring:

- **The balance is always visible and always accurate.** The UX literature on
  bet slips puts "visible stake input, odds changes, balance, payout preview,
  and simple confirmation" together as what makes a slip convert, and says
  "reward UX must stay transparent so players understand cash balance, bonus
  funds, wagering progress, and expiry dates" ([Altenar, sportsbook UX
  trends](https://altenar.com/blog/sportsbook-ux-trends-to-watch/)). The UK
  standards have a whole section on displaying transactions and balances
  ([UKGC RTS 2](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-2-displaying-transactions);
  full text not readable from here).
  **For us:** a balance pill in the top bar on every screen, showing
  withdrawable cash and bonus money *separately*. Never a single merged
  number, because bonus money has playthrough attached and the bonus
  playthrough bug we just fixed shows how much that distinction matters.
- **The bet slip is sticky and survives interruptions.** "Live UX should
  protect in-progress selections, maintaining slip stability even as markets
  move", and mobile needs a "sticky bet slip, and inline deposit"
  ([Altenar, live-play UX](https://altenar.com/blog/how-to-design-a-sportsbook-user-experience-ux-that-wins-in-live-play/)).
  **For us:** Keno picks and stake persist across a reconnect, a round
  change, and a trip to the deposit screen and back. "Deposit" sits inside
  the slip when the balance is short, not in a separate menu.
- **Big thumb targets, primary actions low on the screen.** "Mobile-friendly
  interfaces are characterized by larger buttons, easy scroll functions,
  swipeable menus, and sticky navigation bars", and a mobile-first product
  "keeps core actions close to the thumb"
  ([Symphony Solutions, sportsbook UX](https://symphony-solutions.com/insights/sportsbook-ux)).
- **The lobby is a launcher, not a feed.** "The player enters a lobby,
  chooses between slots or live tables, reads the promotion rules, and tracks
  progress after eligible rounds"
  ([Command Linux, casino gamification UX](https://commandlinux.com/blog/gamification-of-gaming-platforms-the-ux-layer-behind-retention)).
  **For us:** a game centre with one card per game, each showing live state
  (the next Keno draw countdown, the current Bingo lobby fill) and its
  jackpot. The grid has room for a third card without a redesign.
- **"My bets" and recent results are one tap away.** Lottery Keno apps
  advertise "watch the Keno draw live, get instant results, and receive live
  jackpot updates" as the headline features
  ([Tabcorp's Keno app on Google Play](https://play.google.com/store/apps/details?id=au.com.tabcorp.keno&gl=AU)).

### 1.2 The standard layout (recommendation, drawn from the above)

```
┌───────────────────────────────┐
│ ‹ Back   Keno      [ETB 245 ▾]│ ← top bar: Telegram back, title, balance pill
│ Jackpot ETB 12,480  · Draw 0:41│ ← live strip: jackpot + countdown, always
├───────────────────────────────┤
│                               │
│        the game surface       │ ← board / draw
│                               │
├───────────────────────────────┤
│ Picks 6 · Stake 10 · Win ≤ 800│ ← bet slip summary (sticky, expandable)
│ [Quick pick] [Clear] [Auto…]  │
├───────────────────────────────┤
│ [       Place bet ETB 10     ]│ ← Telegram MainButton (native, bottom)
└───────────────────────────────┘
  Tabs: Play · My bets · Results · Stats · ? (how to play / paytable)
```

---

## 2. How established Keno products present the game

### 2.1 Products looked at

| Product | Format | What it shows us | Source |
|---|---|---|---|
| Tabcorp **Keno** (Australia, clubs and app) | 20 from 80, draw every 3 min | Live draw on screen, jackpots, **Heads or Tails** side bet, "Kwikpiks" (quick pick) | [Google Play listing](https://play.google.com/store/apps/details?id=au.com.tabcorp.keno&gl=AU), [Keno Australia rules](https://kenowinningnumbers.com/game/au-keno) |
| NY Lottery **Quick Draw** / NJ Quick Draw | 20 from 80, draw every 4 min, pick 1–10 | Continuous schedule around the clock, fixed top prize, add-on side games | [NY Lottery](https://www.nylottery.org/quick-draw), [NJ Lottery](https://www.njlottery.com/en-us/drawgames/quickDraw.html) |
| **GoldenRace** Keno / Keno Deluxe (B2B, sold into African retail and online) | 20 from 80, pick 1–10 | Extra markets (Even/Odd, Over/Under, Sum), quick pick, **the same bet on up to 22 consecutive events**, operator-configurable paytables, jackpots, a mobile rework in Dec 2025 | [GoldenRace product page](https://goldenrace.com/virtuals/number-games/keno-and-keno-deluxe), [European Gaming, Dec 2025](https://europeangaming.eu/portal/latest-news/2025/12/04/197787/goldenrace-upgrades-its-classic-keno-keno-deluxe-for-mobile/) |
| **Kiron Interactive** via **Hulu Sport** (Ethiopia) | Virtual number games, bandwidth-light mobile | Our actual local competitor set: Kiron built a "Mobile Lite" product "optimized for mobile devices in regions with restricted bandwidth" for Hulu Sport | [Gambling Insider](https://www.gamblinginsider.com/news/25068/kiron-interactive-expands-deal-with-hulu-sport-in-ethiopia), [HuluSport games](https://hulusport.com/games), [Habtam Bet keno](https://habtam.bet/games-list/keno---1) |
| **Stake** Keno (crypto casino "original") | 10 from 40, pick 1–10, instant | Risk profiles, auto-bet, a **provably fair verifier** built into the game | [Stake](https://stake.com/casino/games/keno), [SportsGambler review](https://www.sportsgambler.com/review/stake/keno/), [Jaxon review](https://www.jaxon.gg/gambling/stake-com/keno/) |

### 2.2 The board

- **The 80-number grid, 10 × 8, is the universal convention** for 20-from-80
  games (Tabcorp, Quick Draw, GoldenRace, and the local Ethiopian sites that
  describe the game as "pick up numbers out of 80 and check if they are among
  the 20 numbers randomly drawn" — [HuluSport](https://hulusport.com/games)).
  Our engine already uses 80/20, so the board looks familiar to any
  Ethiopian who has played in a betting shop.
- **Tabcorp's Heads or Tails splits the grid into a top half (1–40) and
  bottom half (41–80)** ([Google Play](https://play.google.com/store/apps/details?id=au.com.tabcorp.keno&gl=AU)).
  Recommendation: draw the grid with a visible divider between rows 4 and 5
  from day one, even though we don't offer the side bet yet, so adding it
  later doesn't change the board's look.
- **Pick states** each need their own look on the board: unpicked, picked,
  drawn-not-picked, drawn-and-picked (a hit). The hit state is the one that
  matters most and must not depend on colour alone (see §2.5).

### 2.3 Picking and staking

- **Quick pick for 1–N spots** is universal (Tabcorp "Kwikpiks", Quick Draw,
  GoldenRace, Stake's "Random Pick"). The honest line every serious guide
  carries: "Whether you use 'Quick Pick' or choose your own Keno numbers, the
  probability remains the same"
  ([Hard Rock Bet, how to play Keno](https://www.hardrock.bet/casino/how-to-play-keno/)).
  We should say that inside the product, not only in a help page.
- **The paytable changes as you pick.** Online Keno shows "the potential
  payouts for that specific game" as you select numbers, and "the paytable is
  displayed before each round"
  ([CasinoBeats, how to play Keno](https://casinobeats.com/features/how-to-play-keno/)).
  Our `renderMatchPaysRows` already does this. The convention to keep: the
  rows for *your* current pick count, with your stake already multiplied in,
  not an abstract table of multipliers.
- **Stake as chips, not a free-text field**, with the maximum win shown
  before confirming. Quick Draw's "minimum play is $1" framing
  ([NY Lottery](https://www.nylottery.org/quick-draw)) is typical: a small
  set of fixed stake steps. Our tiers already work this way.

### 2.4 The draw

- **Live, ball by ball, on a fixed schedule.** Tabcorp every 3 minutes, Quick
  Draw every 4, with a published schedule and a visible countdown. This is
  what separates *draw* Keno (ours: shared rounds, everyone sees the same 20
  numbers) from *instant* Keno (Stake: your own private draw on demand). Ours
  is the draw kind, and that matters for the layout: the countdown has to be
  on screen constantly, and the draw is a shared event people watch
  together, like the Bingo call.
- **Recommendation for the draw animation:** one number at a time, lit on
  the board *and* added to a "drawn so far" strip (20 slots, filling). The
  running hit count ("3 hits") sits next to it. Picked-and-drawn numbers get
  a stronger animation than drawn-only ones. No animation should need more
  than CSS transforms and opacity (see §4.4).
- **Hot and cold numbers are an expected feature, with an honesty caveat.**
  Every mainstream guide describes them as numbers that appeared often or
  rarely in recent games and adds that "past results do not influence future
  draws, and selecting hot or cold numbers does not actually increase or
  decrease your chances"
  ([CasinoBeats](https://casinobeats.com/features/how-to-play-keno/)). We
  already have hot/cold (`loadHotCold`). The caveat line belongs on the same
  screen, in both languages.

### 2.5 The win moment, and what not to copy

- **Losses disguised as wins are banned** in the UK: "sounds or imagery which
  give the illusion of a win when the return is in fact equal to, or below, a
  stake" ([OLBG summary of UK slot rules](https://www.olbg.com/slots/articles/uk-slot-game-regulations);
  the underlying UKGC standard couldn't be opened from here). Ethiopia has no
  such rule that I could find, but we should adopt it anyway: it's the
  honest thing, and it's cheap. Concretely: a Keno ticket that returns less
  than or equal to its stake gets a neutral "returned ETB X" result, **no
  confetti, no win sound, no gold**. Confetti (`spawnConfetti`) only fires
  when payout > stake.
  **The current Mini App does exactly the thing that's banned:**
  `showResult` in `web/miniapp/js/keno.js` sets `won = totalPayout > 0`,
  then shows "+ X ETB" and confetti. An ETB 50 ticket that pays back ETB 20
  currently gets a celebration. The Part C build fixes this; it's a small
  change and could go earlier if you want it to.
- **Speed.** The UK set a 2.5-second minimum per slot spin and banned turbo
  features, because "these features increase the risk of harm"
  ([SBC News](https://sbcnews.co.uk/igaming/2021/02/02/ukgc-bans-online-slots-autoplay-and-quickspin-features/),
  [OLBG](https://www.olbg.com/slots/articles/uk-slot-game-regulations)). Our
  seeded config (migration `c4e8f1a9b6d3`) is a 45 s cycle: 25 s betting,
  12 s draw, 8 s result. That's well above 2.5 s, but it's **4–5× faster than
  the lottery Keno products above** (3 and 4 minutes). It's a legitimate
  choice for an online product, but a fast one, and an argument for making
  multi-race's net-position banner (§2.6) and reality checks (§5) solid.
  Separately, 20 balls in 12 s is 0.6 s per ball, which is tight for a
  readable animation on a cheap phone; the draw design should be built to
  that budget or the operator should consider `draw_seconds` ≈ 16–20.
  Recommendation: no "skip animation" button for the draw.
- **The result stays on screen.** The UK autoplay standard requires that "the
  result of each gamble must be displayed for a reasonable length of time
  before the next gamble commences"
  ([UKGC RTS 8](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-8-autoplay-functionality),
  via search excerpt). Our result banner should stay up until the next
  round's betting opens, even during autoplay.
- **Colour-blind safety.** Hit vs. miss must also differ in shape or icon
  (a ring or a check on hits), not only red/green.

### 2.6 Autoplay and multi-race: honest controls

The industry splits here, and we have to pick a side on purpose:

- **Multi-draw is standard in lottery and retail Keno.** GoldenRace allows
  "the same bets on up to twenty-two consecutive events"
  ([GoldenRace](https://goldenrace.com/virtuals/number-games/keno-and-keno-deluxe)),
  and online Keno sites offer "multi-race" to "play the same set of numbers
  across several consecutive rounds"
  ([CasinoBeats](https://casinobeats.com/features/how-to-play-keno/)).
- **Open-ended autoplay is the part regulators went after.** The UK banned
  autoplay for online slots in 2021, citing its own research: "the majority
  (58%) of auto-play users agreed that auto-play had resulted in them playing
  a game faster than they had intended"
  ([SBC News](https://sbcnews.co.uk/igaming/2021/02/02/ukgc-bans-online-slots-autoplay-and-quickspin-features/)).
  UK RTS 8 more broadly requires the customer to "commit to each game cycle
  individually" for online gaming (search excerpt of
  [RTS 8](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-8-autoplay-functionality)),
  with a 2025 update (RTS 8A) whose detail I couldn't read.

What we already built (`packages/core/keno_autoplay.py`) sits on the
defensible side: a fixed round count (max 100), optional stop-on-win and
stop-on-loss amounts, blocked by the player's responsible-gaming limits.
Recommendations for the UI:

1. Show the **total commitment** before starting: "10 rounds × ETB 10 =
   up to ETB 100", in large type, with the confirm button repeating the total.
2. While running: a persistent banner "Autoplay 4 of 10 · spent ETB 40 · won
   ETB 25 · [Stop]". Stop is always one tap, never behind a menu.
3. Net position ("down ETB 15"), not only gross wins. That matches the UK's
   2025 "net spend" display requirement (RTS 2E / 13C per the
   [2025 update summaries](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-13-time-requirements-and-reality-checks)),
   and it's the number an honest product shows.
4. Call it "Multi-race", not "Autoplay". It's what it actually is: a fixed,
   prepaid-feeling series.

### 2.7 Fairness verification

Stake is the reference for in-game verification: results "can be verified
using cryptographic hashing via the 'Fairness' tab by getting the client
seed and server seed" ([Jaxon, Stake Keno](https://www.jaxon.gg/gambling/stake-com/keno/)),
and a third-party ecosystem of verifiers exists around it
([Stake Analyzer seed checker](https://stakeanalyzer.live/seed-checker/keno),
[Spindex verifier](https://spindex.net/provably-fair/stake/keno)). The lesson
from those third-party tools is that the *data* must be public and the
*algorithm* documented, so anyone can re-derive a draw outside our servers.

We already have the harder half: commit-reveal with `server_seed_hash`
published before betting and a public seed fixed at close
(`docs/keno/06-fairness-and-verification.md`), and a `verifyResult` in the
Mini App. Recommendation for the one-tap flow:

- On every result and every row in My bets: a small "✓ Verify" chip.
- Tapping it shows the published hash, the revealed seed, the public seed,
  the recomputed 20 numbers, and a green "matches" / red "does not match".
  The recomputation runs **in the browser** (Web Crypto HMAC-SHA256), not a
  server call that says "trust me".
- A "verify it yourself" link to a static page with the algorithm and a copy
  button for each input.

### 2.8 The jackpot

Tabcorp and GoldenRace both treat the jackpot as a live, headline number
([Google Play](https://play.google.com/store/apps/details?id=au.com.tabcorp.keno&gl=AU),
[GoldenRace](https://goldenrace.com/virtuals/number-games/keno-and-keno-deluxe)).
Ours is player-funded (1.5% diversion into `keno_jackpot_pool`,
`docs/keno/07-economics-and-bankroll.md`). Recommendations: show it in the
live strip on the Keno screen *and* on the lobby card, update it per round
(not a fake ticking counter — it should only move when real stakes move it),
and link it to a plain-language line about how it's won.

---

## 3. What a real operator back office contains

### 3.1 Sources

| Platform | What its own material lists | Source |
|---|---|---|
| **EveryMatrix GamMatrix** | PAM + wallet, fraud detection, responsible gaming, player tagging, batch processing, "functional roles"; a product-neutral bonus engine shared by casino and sportsbook; reporting with "segmentation, activity, balances, responsible gambling, and jurisdiction-specific reporting" and "50+ filters" | [PAM](https://everymatrix.com/gammatrix/pam/), [Reporting](https://everymatrix.com/gammatrix/reporting/), [Platform features](https://everymatrix.com/gammatrix/platform-features/) |
| **PieGaming** back office | Player management, transactions, content, promotions, risk, reporting | [PieGaming](https://piegaming.com/back-office-system/) |
| **iGP** | What a platform is: PAM, wallet, CMS, back office as separate layers | [iGP](https://igpgaming.com/product/what-is-an-igaming-platform-pam-wallet-cms-back-office/) |
| **Novatrasoft** PAM | "Player 360°": activity, financial behaviour, balances, bonus usage, communications, withdrawal and betting limits, risk indicators, responsible-gaming data in one profile | [Novatrasoft](https://novatrasoft.com/solutions/player-account-management/) |
| **Broadway**, **BigiGameSoft**, **Tecpinion**, **TIG** | Game management, **game provider management**, agent management, affiliate management; real-time reports on "player, game, provider, bets, GGR, KYC" | [Broadway](https://broadwayplatform.com/solutions/backoffice/), [BigiGameSoft](https://bigigamesoft.com/solutions/casino-engine/), [TIG](https://www.tigsoftwares.com/blog/casino-back-office-features-for-operators/) |
| **Spinlab**, **TrueIGTech** | Deposits and withdrawals "belong in one review queue with approval workflows"; the withdrawal view shows "KYC status, payment history, bonus obligations, gameplay behavior, risk signals, responsible gambling limits, and previous support tickets in one workflow" | [Spinlab](https://spinlab.studio/what-is-casino-platform-backoffice-software/), [TrueIGTech](https://www.trueigtech.com/casino-pam-crm-and-back-office-development-solutions/) |

These are vendors describing their own products, so they're marketing
material. They're still useful as a checklist, because they agree closely
with each other.

### 3.2 The standard sections, mapped to the brief

| Industry section | What it holds | Brief's Part D section |
|---|---|---|
| Dashboard / live ops | Live KPIs, alerts, system health | 1. Dashboard |
| Game management (+ provider management) | Enable/disable, config, RTP/paytables, providers | 2. Game management |
| Player account management ("Player 360") | Profile, balances, history, limits, RG, KYC, notes, tags | 3. Players |
| Payments / cashier | Deposit & withdrawal queue with approvals, reconciliation, processor health | 4. Finance |
| Risk & fraud / AML | Surveillance, scoring, alerts, SAR workflow, multi-account | 5. Risk |
| Reporting / BI | GGR, handle, per game/provider/day, cohort, export | 6. Reports |
| Audit / compliance | Who did what, config history, regulator reports | 7. Audit |
| CMS + bonus engine + CRM | Content, banners, promotions, bonuses, messaging, translations | 8. Content |
| Users / roles | Functional roles, granular permissions | 9. Staff |

The brief's nine sections match the industry set almost one-to-one. The one
industry section the brief doesn't name is **agent/affiliate management**. We
already have an agent portal (`web/agent`, `docs/AGENT_DASHBOARD_GUIDE.md`),
so it should get its own entry in the IA rather than being dropped.

### 3.3 Conventions worth adopting

- **One Player 360 page**, not data scattered across screens
  ([Novatrasoft](https://novatrasoft.com/solutions/player-account-management/)).
  Every other section links into it.
- **Withdrawals are decided in context.** The approver sees KYC, payment
  history, bonus obligations, risk signals and RG limits on the same screen
  as the Approve button ([Spinlab](https://spinlab.studio/what-is-casino-platform-backoffice-software/)).
- **Functional roles, not a superuser flag** ([EveryMatrix PAM](https://everymatrix.com/gammatrix/pam/)).
  We already have an RBAC matrix (`docs/RBAC_MATRIX.md`); the brief's "no
  admin=true" points the same way.
- **Maker-checker (four-eyes) for money movement.** I couldn't find a vendor
  page that describes it in detail (search came back thin), so this rests on
  standard financial-controls practice rather than a cited operator:
  adjustments above a threshold need a second person, the maker can't
  approve their own request, and both names and the written reason go into
  the audit log.
- **Providers are data.** Every vendor above lists "game provider management"
  as a back-office section, which only works if adding a provider is a
  registration, not a new screen. That's Part E's admin-extensibility item.

---

## 4. Telegram Mini App conventions

Primary source: the WebApp API type definitions (`@twa-dev/types` 8.0.2 on
npm). Secondary: [Telegram's Mini Apps page](https://core.telegram.org/bots/webapps)
(search excerpt only: interfaces should be "responsive and designed with a
mobile-first approach", should "mimic the style, behavior, and intent of UI
components that already exist", and "all included animations should be
smooth, ideally 60fps"), and [Turumburum's Mini App UX guide](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience).

### 4.1 Use Telegram's own chrome, don't duplicate it

"Simply mirroring a mobile site often leads to duplicated navigation"; the
goal is an app that "feels like a natural, functional extension of the
Telegram ecosystem" ([Turumburum](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience)).
The API gives us:

| API | Use it for |
|---|---|
| `MainButton` (a `BottomButton`: `setText`, `showProgress`, `enable`/`disable`) | The one primary action per screen: "Place bet ETB 10", "Deposit", "Confirm withdrawal". `showProgress` while the request is in flight, which also stops double-taps. |
| `SecondaryButton` (with `position`) | The paired action: "Quick pick" beside "Place bet", or "Cancel" on a confirmation. |
| `BackButton` | Navigation back. No in-page back arrow. |
| `SettingsButton` | Opens settings, including responsible-gaming controls: a place players already know to look. |
| `enableClosingConfirmation()` | On while a bet is in flight or a multi-race is running (we already do this in `updateClosingConfirmation`). |
| `disableVerticalSwipes()` | During the draw and on the number grid, so a swipe across numbers doesn't minimise the app. |
| `HapticFeedback.impactOccurred` / `notificationOccurred` / `selectionChanged` | Pick toggles, bet confirmed, win. Android caveat: a reported bug says `impactOccurred` and `selectionChanged` do nothing on Telegram Android while `notificationOccurred` works ([issue #28](https://github.com/Telegram-Mini-Apps/issues/issues/28)), so haptics must be a bonus, never the only feedback. Firing too often costs battery. |
| `CloudStorage` | Per-player settings that follow them across devices: language, sound on/off, onboarding done. |
| `requestFullscreen()`, `safeAreaInset`, `contentSafeAreaInset` | Fullscreen for the draw is optional; if used, all layout respects both insets. |
| `viewportStableHeight` (vs `viewportHeight`) | Size the layout off the *stable* height so the page doesn't jump while Telegram's sheet is being dragged. |
| `isVersionAtLeast()` | Guard every newer API. Older Telegram clients are common on cheap Android phones. |

### 4.2 Theme-awareness

Telegram passes 15 colour keys in `themeParams`: `bg_color`,
`secondary_bg_color`, `section_bg_color`, `header_bg_color`,
`bottom_bar_bg_color`, `text_color`, `hint_color`, `subtitle_text_color`,
`section_header_text_color`, `link_color`, `accent_text_color`,
`button_color`, `button_text_color`, `destructive_text_color`,
`section_separator_color`, plus `colorScheme: "light" | "dark"`. They're also
exposed as CSS variables (`--tg-theme-bg-color`, etc.).

Recommendation for Part B: **surfaces follow Telegram, game semantics don't.**
Backgrounds, text, separators and the neutral button take Telegram's theme,
so the app looks native in every theme. The things that carry meaning (hit,
drawn, win, loss, warning, the jackpot gold) are our own fixed tokens, in a
light and a dark variant, tested for contrast against both Telegram
defaults, because a player's custom theme must never make a hit look like a
miss.

### 4.3 Language

`initDataUnsafe.user.language_code` gives the Telegram UI language. Use it
only as the *first* guess; the player's in-app choice (stored in
`CloudStorage`) wins. The repo already ships `am`, `en`, `om` and `ti`
locale files and a subset Noto Sans Ethiopic font. Ge'ez script needs more
line-height than Latin at the same size, and Amharic strings often run
longer, so components must wrap rather than truncate.

### 4.4 Cheap Android, slow network

This is the market reality: Kiron built a separate "Mobile Lite" product for
Hulu Sport specifically "for mobile devices in regions with restricted
bandwidth" ([Gambling Insider](https://www.gamblinginsider.com/news/25068/kiron-interactive-expands-deal-with-hulu-sport-in-ethiopia)).
Our local competitor's supplier treated low bandwidth as a first-class
product requirement. Recommendations:

- A budget: first screen interactive in under 3 s on a slow 3G profile,
  initial JS+CSS under ~150 KB compressed, fonts subset (already done for
  Ethiopic).
- Draw animation only via `transform` and `opacity`, no layout-triggering
  properties, no canvas or WebGL, and a reduced-motion path
  (`prefers-reduced-motion`) that still shows each number.
- The draw is driven by WebSocket events, but the board state is rebuilt
  from `GET /api/keno/state` on every reconnect, so a dropped connection
  mid-draw recovers to the right picture instead of replaying.
- Sounds are short, preloaded after the first interaction, off by default on
  first launch (a Telegram chat is often opened in public), and one toggle
  away.

---

## 5. Responsible-gaming controls players can actually find

Industry-standard set, as consumer guides describe them
([Casino.Guru](https://casino.guru/usa/responsible-gambling),
[igamingxp](https://igamingxp.com/responsible-gambling-tools-self-exclusion/),
[iGaming.com on reality checks](https://www.igaming.com/igamingcare/reality-checks/)):

- **Deposit limits** by day/week/month: "can typically be lowered at any
  time, but increases usually require a cooling-off period".
- **Cool-off**: a short, self-imposed lock (24 hours to 6 weeks) where the
  account stays open.
- **Reality checks**: periodic pop-ups with time played and, ideally, net
  win/loss. They "don't block play but help interrupt long sessions".
- **Self-exclusion**: a longer lock that can't be undone early.
- **A session clock** where the app covers the phone's own clock (UK RTS 13,
  via [search excerpt](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-13-time-requirements-and-reality-checks)).
  A Telegram Mini App in fullscreen does hide the status bar, so this
  applies to us.

Recommendation: reachable from three places (the `SettingsButton`, the
balance pill menu, and a link at the bottom of every game screen), and
worded as a normal feature ("Set a limit"), not buried under "Legal". Our
engine already enforces loss limits for autoplay
(`AutoplayBlockedByResponsibleGaming`); `docs/RESPONSIBLE_GAMING_REQUIREMENTS.md`
holds the current requirements.

### 5.1 The Ethiopian regulatory picture (flag for the operator)

Search results report that:

- the minimum gambling age in Ethiopia is **21**
  ([CMS Expert Guide](https://cms.law/en/int/expert-guides/cms-expert-guide-to-gambling-laws-in-africa/ethiopia),
  [gamblingmaps](https://gamblingmaps.org/map/regulations/ethiopia));
- sports betting is governed by the "Sports Betting Lottery Directive No.
  172/2021" ([Slotegrator](https://slotegrator.pro/analytical_articles/online-gambling-in-ethiopia/));
- **Ethiopia withdrew all sports-betting operators' licences with effect from
  15 December 2025** ([SiGMA](https://sigma.world/news/ethiopia-revokes-all-sports-betting-licences/)),
  with a later National Lottery Administration statement about cessation not
  being required ([2merkato](https://www.2merkato.com/news/alerts/7697-ethiopia-cessation-of-sports-betting-not-required-national-lottery-administration)).
  I could only read excerpts and couldn't establish the current state.

This bears directly on Part E's sports-betting sketch and on age-gating in
onboarding. I'm not qualified to interpret it and haven't tried to. It
needs a check by someone who knows the current NLA position before any
sports work is costed seriously.

---

## 6. Where we are against these conventions

What already exists (from reading the code), and what the conventions ask
for on top.

| Convention | Today | Gap |
|---|---|---|
| Balance always visible, cash and bonus separate | Wallet screens exist | Persistent balance pill on the Keno screen; cash/bonus split everywhere |
| Sticky bet slip that survives interruptions | Picks + stake + payout rows (`renderPicksAndPayout`) | Survive reconnect / deposit round-trip; inline "deposit" when short |
| Lobby with room for a third game | Separate Bingo and Keno entry points | Game centre driven by a game registry (Part E) |
| 80-grid, 4 pick states, colour-blind safe | Grid with hot/cold overlay | Shape/icon for hits; half-grid divider |
| Paytable for *my* picks | Yes (`renderMatchPaysRows`, `openPaytable`) | Always one tap away; include hit frequency in plain language |
| Live draw, ball by ball | Draw rendering in `keno.js` | Drawn strip + running hit count; reduced-motion path; rebuild from state on reconnect |
| No loss disguised as a win | Confetti and "+X ETB" on **any** payout > 0, including payouts below the stake | Celebrate only when payout > stake; neutral "returned" state |
| Honest multi-race | Server-side sessions, max 100, stop-on-win/loss, RG-gated | Total-commitment confirm; persistent net-position banner; rename |
| One-tap verify, computed client-side | `verifyResult` exists | Chip on every result and bet; in-browser recompute; public algorithm page |
| Live jackpot | Pool exists in the ledger | On the lobby card and the live strip, moves only on real stakes |
| RG controls easy to find | RG enforcement exists server-side | SettingsButton + balance menu entry; reality checks; session clock in fullscreen |
| Onboarding a beginner can follow | Onboarding steps (`openOnboarding`) | Age-21 statement; interactive first ticket |
| Back office as its own app, 9 sections + agents | `web/admin` with ~25 screens incl. Keno | Rebuild as its own app per Part D; Player 360; maker-checker; registry-driven game/provider screens |

## Sources

Search excerpts unless marked otherwise.

- Telegram: `@twa-dev/types` 8.0.2 on npm (**read in full**);
  [Telegram Mini Apps](https://core.telegram.org/bots/webapps);
  [Turumburum Mini App UX guide](https://turumburum.com/blog/telegram-mini-app-beyond-the-standard-ui-designing-a-truly-native-experience);
  [Telegram-Mini-Apps issue #28 (Android haptics)](https://github.com/Telegram-Mini-Apps/issues/issues/28)
- Keno products: [Tabcorp Keno (Google Play)](https://play.google.com/store/apps/details?id=au.com.tabcorp.keno&gl=AU);
  [Keno Australia rules](https://kenowinningnumbers.com/game/au-keno);
  [NY Lottery Quick Draw](https://www.nylottery.org/quick-draw);
  [NJ Lottery Quick Draw](https://www.njlottery.com/en-us/drawgames/quickDraw.html);
  [GoldenRace Keno & Keno Deluxe](https://goldenrace.com/virtuals/number-games/keno-and-keno-deluxe);
  [European Gaming on GoldenRace's mobile Keno](https://europeangaming.eu/portal/latest-news/2025/12/04/197787/goldenrace-upgrades-its-classic-keno-keno-deluxe-for-mobile/);
  [Stake Keno](https://stake.com/casino/games/keno);
  [SportsGambler on Stake Keno](https://www.sportsgambler.com/review/stake/keno/);
  [Jaxon on Stake Keno](https://www.jaxon.gg/gambling/stake-com/keno/);
  [Stake Analyzer seed checker](https://stakeanalyzer.live/seed-checker/keno);
  [Spindex verifier](https://spindex.net/provably-fair/stake/keno);
  [CasinoBeats, how to play Keno](https://casinobeats.com/features/how-to-play-keno/);
  [Hard Rock Bet, how to play Keno](https://www.hardrock.bet/casino/how-to-play-keno/)
- Ethiopian market: [Gambling Insider on Kiron × Hulu Sport](https://www.gamblinginsider.com/news/25068/kiron-interactive-expands-deal-with-hulu-sport-in-ethiopia);
  [HuluSport games](https://hulusport.com/games);
  [Habtam Bet keno](https://habtam.bet/games-list/keno---1);
  [CMS Expert Guide, Ethiopia](https://cms.law/en/int/expert-guides/cms-expert-guide-to-gambling-laws-in-africa/ethiopia);
  [SiGMA on licence revocation](https://sigma.world/news/ethiopia-revokes-all-sports-betting-licences/);
  [2merkato on NLA statement](https://www.2merkato.com/news/alerts/7697-ethiopia-cessation-of-sports-betting-not-required-national-lottery-administration);
  [Slotegrator on Ethiopia](https://slotegrator.pro/analytical_articles/online-gambling-in-ethiopia/);
  [gamblingmaps, Ethiopia](https://gamblingmaps.org/map/regulations/ethiopia)
- Player-facing UX: [Altenar, sportsbook UX trends](https://altenar.com/blog/sportsbook-ux-trends-to-watch/);
  [Altenar, live-play UX](https://altenar.com/blog/how-to-design-a-sportsbook-user-experience-ux-that-wins-in-live-play/);
  [Symphony Solutions, sportsbook UX](https://symphony-solutions.com/insights/sportsbook-ux);
  [Command Linux, casino gamification UX](https://commandlinux.com/blog/gamification-of-gaming-platforms-the-ux-layer-behind-retention)
- Regulation and RG: [UKGC RTS 2](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-2-displaying-transactions);
  [UKGC RTS 8](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-8-autoplay-functionality);
  [UKGC RTS 13](https://www.gamblingcommission.gov.uk/standards/remote-gambling-and-software-technical-standards/rts-13-time-requirements-and-reality-checks);
  [SBC News on the UK autoplay ban](https://sbcnews.co.uk/igaming/2021/02/02/ukgc-bans-online-slots-autoplay-and-quickspin-features/);
  [OLBG on UK slot rules](https://www.olbg.com/slots/articles/uk-slot-game-regulations);
  [Casino.Guru RG tools](https://casino.guru/usa/responsible-gambling);
  [igamingxp RG tools](https://igamingxp.com/responsible-gambling-tools-self-exclusion/);
  [iGaming.com on reality checks](https://www.igaming.com/igamingcare/reality-checks/)
- Back office: [EveryMatrix PAM](https://everymatrix.com/gammatrix/pam/);
  [EveryMatrix reporting](https://everymatrix.com/gammatrix/reporting/);
  [EveryMatrix platform features](https://everymatrix.com/gammatrix/platform-features/);
  [PieGaming](https://piegaming.com/back-office-system/);
  [iGP](https://igpgaming.com/product/what-is-an-igaming-platform-pam-wallet-cms-back-office/);
  [Novatrasoft PAM](https://novatrasoft.com/solutions/player-account-management/);
  [Broadway](https://broadwayplatform.com/solutions/backoffice/);
  [BigiGameSoft](https://bigigamesoft.com/solutions/casino-engine/);
  [TIG](https://www.tigsoftwares.com/blog/casino-back-office-features-for-operators/);
  [Spinlab](https://spinlab.studio/what-is-casino-platform-backoffice-software/);
  [TrueIGTech](https://www.trueigtech.com/casino-pam-crm-and-back-office-development-solutions/)
