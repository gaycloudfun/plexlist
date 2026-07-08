# Structly — Idea Board

---

## Brand System
- **Name:** Structly
- **Domain:** structly.app
- **Tagline:** Structure your stream.
- **CTA:** Stop scrolling. Start structuring.
- **Colors:** Black + Orange (#E5A00D) + white text
- **Style:** Editorial, minimal, high whitespace, grid-based
- **Tone:** Confident, clean, structured
- **Core Concept:** Bring order to chaotic media consumption
- **Freemium Gate:** 10 free playlists → unlock full library
- **Limit Message:** "You've structured 10 playlists. Unlock your full library to keep structuring."

---

## In Progress
- [x] Core playlist builder (folder structure + technical metadata)
- [x] macOS app with elegant UI
- [x] Custom Plex-branded icon
- [x] Dock + Applications install

---

## Next Up

### Smart Playlist Features
- [ ] **Filename parser** — extract performer names from filenames, build performer playlists
- [ ] **Auto-scheduler** — rebuild playlists nightly/weekly automatically (no manual clicking)
- [ ] **Tag editor** — let user rename or merge studio names before building playlists
- [ ] **Playlist rules UI** — let user define custom rules in the app (e.g. "only include files over 1GB")

### Analytics & Stats
- [ ] **Library dashboard** — total runtime, resolution breakdown, studio breakdown charts
- [ ] **Most recently added** — auto-playlist of last 30/60/90 days of additions
- [ ] **Duplicate detector** — flag files that appear to be duplicates by name/size

### Multi-Library Support
- [ ] Extend to Movies and TV Shows libraries with genre/year/rating playlists
- [ ] Per-library settings (different PORN_ROOT paths, different rules)

---

## Bigger Ideas

### Sharing & Distribution
- [ ] **Web app (structly.app)** — primary product, Plex OAuth login, runs in browser, any OS
- [ ] **Direct download (.dmg)** — sell Mac app via Gumroad or Stripe direct
- [ ] **Mac App Store** — requires Apple Developer ($99/yr), sandboxing rewrite — lower priority
- [ ] **iOS / iPadOS companion** — trigger playlist builds from your phone

### Infrastructure
- [ ] **Railway** — hosting for web app backend
- [ ] **Stripe** — payments, freemium gate, Pro upgrades
- [ ] **Plex OAuth** — register app at plex.tv/api for "Sign in with Plex"

### Monetization Options
- [ ] One-time purchase via Gumroad ($5–15)
- [ ] Subscription with auto-sync scheduler ($2–5/month)
- [ ] Free core app, paid "Pro" unlock for scheduler + analytics

### Full SaaS Vision — "Structly Plex" (long-term, not scoped yet)

Captured 2026-07-07 as a future-vision reference, not a near-term build. Explicitly
NOT what's being built now — the current priority is the local web UI test
(`docs/superpowers/specs/2026-07-07-web-ui-design.md`) to get real traction
numbers before taking on hosting/accounts/billing cost, per this morning's
approved plan.

A polished, hosted multi-tenant SaaS product, separate brand treatment (bold,
colorful, techy, premium SaaS feel — different from the current
Structured/Precise/Efficient orange-on-black brand in `PRODUCT.md`):

- **Accounts & auth** — signup/login, multi-user, per-account Plex connections
- **Plex OAuth connect flow** — "Sign in with Plex," auto-detect libraries
  (Movies, TV, Music, Other Videos, Adult Only, Home Movies, Misc)
- **Onboarding wizard** — connect → select libraries → choose playlist
  toggles → enable/skip AI Mode → review first scan → publish
- **AI Mode** — LLM-driven analysis of titles/metadata/filenames/folders to
  suggest mood-based playlists ("Rainy Night Thrillers"), duplicate/orphan
  detection, cleanup suggestions; all AI output editable before applying
- **Collections Engine** — auto-built smart collections (franchise, cast,
  director, genre, rating, year, studio, custom rules) plus manual curation
- **Archive & Resurrect** — archive playlists without deleting, one-click
  restore, archive history/last-used tracking
- **Metadata enhancement** — public movie/TV DB enrichment; optional
  opt-in AO metadata scraping for adult content with privacy-first framing
- **Dashboard** — library health score, suggested/active/archived
  playlists, recent changes, AI recommendations, upgrade CTA
- **Notifications** — email/in-app/push for new media, suggestions ready,
  weekly structure report, metadata issues, unused archives, trial ending
- **Monetization** — Free tier (1 server, 2 libraries, 5 playlists, basic
  folder playlists, limited AI) vs. Structly Pro (unlimited everything, AI
  Mode, Collections Engine, Archive & Resurrect, scheduled scans, adult/home
  movie classification, priority support); soft upgrade prompts, locked
  premium cards, monthly/annual upgrade modal
- **Admin console** — user counts, free/Pro split, active connections,
  playlist/AI usage, conversion/churn, support tickets, user search,
  account disable
- **Data models** — Users, Plex Servers, Libraries, Media Items, Playlists,
  Collections, AI Suggestions, Archived Playlists, Scans, Notifications,
  Plans/Subscriptions, Admin Users
- **Pages** — Landing, Signup/Login, Onboarding, Connect Plex, Library
  Selection, Playlist Setup, AI Review, Dashboard, Playlist Detail,
  Collections, Archive, Settings, Billing, Admin Console

If this ever gets prioritized, it needs decomposition into separate specs
per subsystem (auth, Plex-connect, playlist core, AI pipeline, billing,
notifications, admin console) — it is not a single implementation plan.

---

## Notes
- Mac App Store may be restrictive for this use case — direct .dmg distribution is simpler and keeps 100% revenue
- A rewrite in Swift/SwiftUI would be needed for proper App Store sandboxing
- Current PyInstaller build works great for direct distribution
