# Shared context: Summer 2028 IB networking

## How to distribute this packet

There are exactly three active instruction documents in the shared campaign folder `Networking Workflow`. Give Claude this document plus `CLAUDE_IB_RESEARCH_WORKFLOW.md`. Give Codex this document plus `CODEX_IB_OUTREACH_WORKFLOW.md`. Neither agent needs the other agent's instructions, `SETUP_STATUS_2026-09-26.md`, or any archived planning document. Operational paths such as `Networking Handoffs/` and `Trackers/` are relative to the parent `Recruiting` folder, not to `Networking Workflow/`. The live workbooks, résumé, Gmail, `find_work_email.py`, browser sessions, and `Networking Handoffs/research_pool.json` are operational inputs, not additional instruction documents.

This shared context governs campaign facts and cross-agent rules; the companion governs that agent's actions. New explicit instructions from {OWNER_NAME} override older defaults. Do not activate sending merely because these documents were uploaded.

**2026-09-27 update:** the four dated handoff files (`YYYY-MM-DD-claude-research*.json`) were consolidated one time into a single rolling file, `Networking Handoffs/research_pool.json`, which replaces the dated-handoff contract described below. See "The pool file" section. This also collapsed Codex's three city-window sends into one daily run, and added a two-provider-agreement rule for accept-all domains. Everything else in this document is unchanged.

## Candidate and personalization

{OWNER_NAME} is a {CLASS_YEAR} student targeting Summer 2028 IB Summer Analyst roles. Reconfirm his current year and résumé facts at setup. His previously reported GPA was on file; treat it as potentially outdated, not as a screening fact or an email talking point. Never mention high school. Do not invent his major, fraternity, hometown, experience, or shared interests. Ask {OWNER_NAME} to supply/confirm missing personalization facts once during setup and record them in this section of both agents' identical context copy. Without a verified fact, do not claim the connection.

Same major, fraternity, or hometown is strongest; school is strong; shared interests are weak. Analysts and associates are the main targets. VPs and MDs qualify selectively with a genuine connection or specific reason. BB/large-platform and MM outreach take priority over selective EB outreach. Do not describe any EB as easy to enter.

## Schedules and ownership

The campaign has two separate stages, executed in order:

1. [Claude research workflow](CLAUDE_IB_RESEARCH_WORKFLOW.md) runs **twice daily, at 3:00 a.m. and 6:00 a.m. Eastern**, including weekends, as two independent scheduled runs that both update the same pool file. Claude manually reviews LinkedIn profiles, rotates the 40 target firms, finds and verifies company emails with `find_work_email.py` (Prospeo → Hunter → GetProspect → Tomba → MineLead), and updates the shared pool file in place. Claude does not email people or change either tracker.
2. [Codex outreach and tracker workflow](CODEX_IB_OUTREACH_WORKFLOW.md) sends **up to 10 initial emails per day, Monday–Thursday, in one run at 10:00 a.m. Eastern: up to 40 per week.** No initial sends Friday–Sunday. It reads the pool file's `READY` candidates in priority order, checks Gmail and both trackers, reconciles Gmail Sent, and owns all tracker writes. Codex does not repeat email finding.

The pool file is a candidate list, not permission to send. Codex checks every candidate against Gmail and both trackers before sending. {OWNER_NAME} handles replies, meeting scheduling, LinkedIn messages, and all follow-up emails.

## Two separate trackers

- **Outreach tracker — `Trackers/Outreach Tracker.xlsx`:** research candidates accepted by Codex, initial emails, unanswered outreach, follow-up reminders, bounces, suppression, and permanent send history. Created 2026-09-26; not the main recruiting tracker.
- **Main tracker — `Trackers/Recruiting Tracker.xlsx`:** its networking sheets contain only people who have actually replied or reached back. `Connections & Networking` holds those contacts; `Networking Chats` holds their dated interactions and call notes. Application-tracking sheets are unchanged.
- **Tracker digest — `Networking Handoffs/tracker_digest.json`:** a small file Codex regenerates after every send run, holding just active send/reply history and bank/group cooldowns. Claude reads this instead of opening either full workbook on a normal research run, to avoid parsing a 190KB+ file daily.

A genuine human reply qualifies, including a decline or referral; record its actual outcome rather than labeling every response a positive relationship. Automated replies, out-of-office notices, delivery receipts, and bounces do not qualify. Copy/upsert responders into the main tracker, but retain their outreach history in the separate tracker. Deduplicate across both trackers, Gmail, and the pool file. Codex's companion document contains the full tracker schema, promotion, and migration safeguards.

The 40-firm target list below and the two workbooks are shared references. New York and Chicago are primary; San Francisco, Houston, and Philadelphia are secondary. The plan targets Summer 2028 U.S. Investment Banking Summer Analyst recruiting. Five completed calls from 40 initial emails requires 12.5% eventual conversion; measure actual outreach cohorts rather than assume that result.

These documents specify the PC schedules and pool-file contract. They do not themselves create or activate scheduled tasks. Before launch, verify the configured résumé source and Penn Gmail sender, confirm `find_work_email.py` can run and reach its providers, point both agents to the same synced `Networking Handoffs` directory, and test the pool file without sending. See `SETUP_STATUS_2026-09-26.md` for prior status and unresolved launch gates.

## Setup values to complete on the PC

- Shared campaign folder: **`{CAMPAIGN_ROOT}`**. The shared handoff directory is `{CAMPAIGN_ROOT}\Networking Handoffs`; both tracker workbooks are in `{CAMPAIGN_ROOT}\Trackers`.
- Exact Penn sender address: **`{SENDER_EMAIL}`**. The connected School Gmail account and a recent Sent message both show this `From` address (verified 2026-09-26). A Gmail-interface message contained {OWNER_NAME}'s signature; connector-created drafts/sends have not been shown to add that signature automatically. Inspect the actual pilot draft and Sent copy before relying on it.
- Canonical maintained résumé source: **`{CAMPAIGN_ROOT}\Resumes\{RESUME_FILENAME}.docx`**. {OWNER_NAME} directed Codex on 2026-09-26 to use the most updated and recent résumé and confirmed that the current-role internship has not ended. The corresponding Word-exported, visually checked attachment is `{CAMPAIGN_ROOT}\Resumes\{RESUME_FILENAME}.pdf`. Re-export from the Word source if it changes.
- Personalization facts from the selected résumé: **{CLASS_YEAR}; {MAJOR}; {ORG_AFFILIATIONS}; {CURRENT_ROLE}.** These are source-backed for drafting, subject to person-specific relevance. Hometown remains unverified; do not infer it from the Philadelphia location. Interests listed on the selected résumé are {PERSONAL_INTERESTS}; use only when genuinely relevant.
- Reminder destination: **this Codex chat via the `Recruiting follow-up reminders` heartbeat at 9:00 a.m. local Eastern time**. It is currently **PAUSED** while the requested GPT Luna model setting is unresolved. When resumed, it reports only due or overdue seven-day outreach and post-call follow-ups, and never sends email or edits trackers.

Both agents must use the same version of this context. Research may continue with explicitly unverified personal fields; sending remains blocked until required account, résumé, tracker and scheduling checks pass. Scheduled runs and integrations must be tested on the PC; these documents do not establish that they work.

## The pool file (replaces the dated-handoff contract)

`Networking Handoffs/research_pool.json` is the single, continuously-updated list of every candidate either agent has ever researched. Claude appends and updates rows; Codex reads `READY` rows and marks them `SENT`. Nothing is deleted. Required per-candidate fields: `contact_id` (stable slug), `priority_rank` (unique among `READY` rows, null otherwise), `name`, `firm`, `parent_bank`, `city`, `ib_group` (null only when `group_status` is `unverified`), `group_status`, `connection_type` (`school`/`fraternity`/`hometown`/`interest`/`none`), `connection_evidence`, `specific_reason`, `linkedin_url`, `company_email`, `email_source`, `email_verification_state` (`verified`, `accept_all_2plus_agree`, `accept_all_domain`, `not_found`, `not_found_after_3_attempts`, or `unverified_employment`), `profile_checked_at_et`, `status` (`READY`/`PENDING_EMAIL`/`PENDING_CATCHALL_RECHECK`/`EXCLUDED`/`SENT`), and (once sent) `sent_at_et`/`gmail_message_id`. Keep one candidate per unique LinkedIn profile URL and one unique verified company email.

**Catch-all-domain rule:** a domain flagged `accept_all` by the finder script cannot be confirmed for one specific address by a single provider. Rather than excluding the candidate outright, re-run the lookup (or check a second provider) — if 2 or more providers independently return the identical address, mark `email_verification_state: "accept_all_2plus_agree"` and set `status: "READY"`. This is the only path by which a catch-all-domain candidate (JPMorgan, Citi, Jefferies, TD Securities, HSBC, and similar large banks all use catch-all mail domains) can ever become sendable — without it, several top-tier target firms are permanently unreachable under this campaign. Codex caps sends to `accept_all_2plus_agree` addresses at 2 per day as a bounce-risk control, and the existing "stop after 2 hard bounces" rule still applies on top of that cap.

`Networking Workflow/outreach_preflight.py --validate-pool [path]` checks a pool file against this contract (unique ranks and identities, sendable email states and providers, the one-READY-per-bank-and-group cap). Claude runs it on its working copy before every write-back; Codex runs it before selecting candidates. A PASS is a contract check, not permission to send.

Claude's final run summary should report: total `READY` candidates in the pool, how many are new this run, firms/cities searched, and any material gap.

## Shared 40-firm search universe

These are carried-forward search leads, not newly verified office or Summer 2028 program claims. The 24/10/6 buckets preserve the requested allocation; they are campaign buckets, not a definitive industry taxonomy. The 24-name bucket contains eight conventional BBs plus other large platforms. Office labels are search hypotheses. Search Philadelphia where current person-level evidence supports it even if omitted from a firm's suggested offices. Do not expand beyond these 40 without {OWNER_NAME}'s direction.

## Key principles

- **U.S. investment banking only** — roles in advisory/M&A, restructuring, industry coverage, and capital markets within investment banking divisions. Exclude trading, research, asset management, and commercial banking.
- **Five target cities** — New York and Chicago are primary. San Francisco, Houston, and Philadelphia are secondary. Aim for roughly 80% of outreach in New York/Chicago over time, adjusting for actual qualified matches; this is an operating target, not a daily quota.
- **Verify presence before outreach** — city labels in the table are search hypotheses, not proof of a current team or Summer 2028 opening. Confirm the banker's current office and IB role; check the firm's careers page separately for internship availability when applications become relevant.
- **Prioritize tier first** — network broadly within BB and MM firms before pursuing EB positions. EBs are selective; pursue only when you have a warm connection or strong reason.
- **One active cold-outreach thread per parent bank and IB group** across offices and brands. Check for an unanswered initial email or pending follow-up before selecting another teammate. After that sequence ends without a reply, wait at least 21 days from the initial email before trying another person in the same bank/group; a warm introduction can justify an exception.

## 24 bulge-bracket and large global platform targets (60%)

Office labels below indicate where to search first and require person-level verification.

| # | Firm | Practical category | Target offices | Primary focus |
|---:|---|---|---|---|
| 1 | Goldman Sachs | Bulge bracket | NY, Chicago, SF, Houston | Global investment bank; broad M&A and coverage platform |
| 2 | J.P. Morgan | Bulge bracket | NY, Chicago, SF, Houston | Global investment bank; broad sector and product coverage |
| 3 | Morgan Stanley | Bulge bracket | NY, Chicago, SF, Houston | Global investment bank; strong M&A and industry coverage |
| 4 | Bank of America | Bulge bracket | NY, Chicago, SF, Houston | Global investment bank; broad U.S. coverage and capital markets |
| 5 | Citi | Bulge bracket | NY, Chicago, SF | Global investment bank; broad international and U.S. coverage |
| 6 | Barclays | Bulge bracket | NY, Chicago | Global investment bank with U.S. investment banking teams |
| 7 | Deutsche Bank | Bulge bracket | NY, Chicago | Global investment bank with U.S. coverage and product teams |
| 8 | UBS | Bulge bracket | NY, San Francisco, Chicago | Global investment bank; U.S. advisory and capital markets teams |
| 9 | Wells Fargo | Large U.S. bank | NY, SF, Houston | Major U.S. corporate and investment banking platform; BB classification varies |
| 10 | RBC Capital Markets | Large global bank | NY, Chicago, SF, Houston | Large North American corporate and investment banking platform |
| 11 | Jefferies | Large independent investment bank | NY, Chicago, SF, Houston | Broad global investment banking and markets platform |
| 12 | BMO Capital Markets | Large Canadian / U.S. bank | NY, Chicago | Major North American corporate and investment banking platform |
| 13 | CIBC Capital Markets | Large Canadian / U.S. bank | NY, Chicago, SF | North American investment banking and capital markets |
| 14 | TD Securities | Large Canadian / U.S. bank | NY, Chicago | North American corporate and investment banking platform |
| 15 | BNP Paribas | Large global bank | NY, Houston | Global investment banking platform with U.S. teams |
| 16 | HSBC | Large global bank | NY, Chicago, Houston | International corporate and investment banking platform |
| 17 | Mizuho | Large global bank | NY, Chicago, SF, Houston | U.S. investment banking platform, including advisory and financing |
| 18 | Nomura | Large global bank | NY, Chicago, SF | Global investment banking with U.S. advisory and capital markets teams |
| 19 | Guggenheim Securities | Large independent investment bank | NY, Chicago, SF, Houston | U.S. advisory platform with a broad sector and product footprint |
| 20 | KeyBanc Capital Markets | Large U.S. regional bank | NY, Chicago, Houston | U.S. corporate and investment banking platform with analyst recruiting |
| 21 | Oppenheimer & Co | Large independent investment bank | NY, Chicago | U.S. investment banking and capital markets platform |
| 22 | William Blair | Large independent investment bank | Chicago, NY, SF | Advisory and capital markets with substantial U.S. presence |
| 23 | Piper Sandler | Large U.S. regional investment bank | NY, Chicago, SF, Houston | Strong sector coverage and investment banking platform |
| 24 | Stifel | Large U.S. regional investment bank | NY, Chicago, SF, Houston | Broad U.S. investment banking and capital markets |

## 6 selected elite boutiques (15%)

Office labels below indicate where to search first and require person-level verification.

| # | Firm | Practical category | Target offices | Primary focus |
|---:|---|---|---|---|
| 25 | Evercore | Elite boutique | NY, Chicago, SF, Houston | Independent advisory, including M&A and restructuring |
| 26 | Lazard | Elite boutique | NY, Chicago, SF | Independent financial advisory and restructuring |
| 27 | Moelis & Company | Elite boutique | NY, Chicago, SF, Houston | Independent global advisory firm |
| 28 | PJT Partners | Elite boutique | NY, Houston, Chicago | Independent advisory, restructuring, and strategic solutions |
| 29 | Centerview Partners | Elite boutique | NY, SF | Independent strategic advisory |
| 30 | Perella Weinberg Partners | Elite boutique | NY, SF, Houston | Independent advisory and restructuring |

## 10 middle-market targets (25%)

Office labels below indicate where to search first and require person-level verification.

| # | Firm | Practical category | Target offices | Primary focus |
|---:|---|---|---|---|
| 31 | Houlihan Lokey | Middle market | NY, Chicago, SF, Houston | Broad advisory platform; especially strong in M&A, restructuring, and valuation |
| 32 | Baird | Middle market | Chicago, NY, SF | U.S. middle-market investment banking and advisory |
| 33 | Raymond James | Middle market | NY, Chicago, SF, Houston | U.S. investment banking platform with sector coverage |
| 34 | Harris Williams | Middle market | NY, Chicago, SF, Houston | M&A advisory focused on middle-market companies |
| 35 | Lincoln International | Middle market | NY, Chicago, Houston | Global M&A and financial advisory; Philadelphia presence |
| 36 | Rothschild & Co | Middle market | NY, Chicago | Independent financial advisory and M&A |
| 37 | Ducera Partners | Middle market | NY, Chicago, Houston | M&A advisory, restructuring, and strategic solutions |
| 38 | Citizens Capital Markets & Advisory | Middle market | NY, SF | Middle-market investment banking and advisory; confirm office and group for each banker |
| 39 | Canaccord Genuity | Middle market | NY, Chicago, SF | U.S. investment banking; confirm office, group, and Summer 2028 program |
| 40 | Solomon Partners | Middle market | NY, Chicago, SF, Houston | M&A and financial advisory platform |

Greenhill Advisory is a team-search term under Mizuho; Miller Buckfire/Capital Structure Advisory is a team-search term under Stifel. Reverify current affiliations before outreach and apply the parent-bank/group rule.
