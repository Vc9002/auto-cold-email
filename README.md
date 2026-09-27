# auto-cold-email

A two-agent, no-send-by-default networking research and outreach toolkit for
IB (or any professional) cold-networking campaigns: one agent researches and
sources verified contact emails, a second agent sends and tracks outreach,
and a local Python gate enforces the campaign's rules before anything goes
out.

This repo is a **template**. Every personal detail (name, sender email,
résumé filename, school/employer facts, existing contacts) has been
replaced with a placeholder — fill in your own via the config points listed
below before running this for real. Nothing here sends email on its own,
and no API keys or personal campaign data (trackers, handoffs, résumés) are
committed to this repo — see `.gitignore`.

## Structure

```
docs/
  claude-research-workflow.md   Research-agent instructions: source and
                                 verify candidates, find company emails,
                                 update the rolling research_pool.json.
                                 Never sends.
  codex-outreach-workflow.md    Outreach-agent instructions: send to READY
                                 pool rows, mark them SENT, own the
                                 trackers, handle replies/follow-ups.
  networking-context.md         Shared campaign facts + the pool-file
                                 contract both agents must agree on.
scripts/
  find_work_email.py            Cascading company-email finder used by the
                                 research workflow: Prospeo -> Hunter ->
                                 GetProspect -> Tomba -> MineLead, first hit
                                 wins, with local caching and per-provider
                                 monthly quota tracking so a repeat lookup
                                 never costs a credit twice. --all-providers
                                 asks every provider (catch-all recheck) and
                                 reports whether 2+ agree.
  outreach_preflight.py         No-send local gate. --validate-pool checks
                                 research_pool.json against the contract
                                 (unique ranks/identities, sendable email
                                 states, one READY per bank/group). The
                                 default mode validates the older dated-
                                 handoff format.
  test_outreach_preflight.py    Test suite for the preflight gate.
```

## Configuring it for yourself

The docs use these placeholders — replace them with your own values
wherever they appear:

| Placeholder | What it means |
|---|---|
| `{SENDER_EMAIL}` | The email address outreach actually sends from |
| `{OWNER_EMAIL}` | Your own identifying email (used for e.g. API account lookups) |
| `{CAMPAIGN_ROOT}` | Absolute path to your campaign folder (trackers, handoffs, résumés) |
| `{CLASS_YEAR}`, `{MAJOR}`, `{ORG_AFFILIATIONS}`, `{CURRENT_ROLE}` | Personalization facts pulled from your résumé, used only where a genuine connection applies |
| `{PERSONAL_INTERESTS}` | Interests you're comfortable referencing in outreach |
| `{RESUME_FILENAME}` | Base filename (no extension) of your canonical résumé |
| `{EXISTING_CONTACT_NAMES}` | Names already in your main tracker before this campaign started |
| `{CURRENT_EMPLOYER}` | Your current internship/job, if relevant to your outreach angle |

`scripts/outreach_preflight.py` reads `RESUME_BASENAME` from the environment
(defaults to `Resume`) instead of a hardcoded name — set it to your actual
résumé's base filename.

## Email-finder setup

`scripts/find_work_email.py` reads provider API keys from a local folder
(never committed — see `.gitignore`), one file per provider:

```
.prospeo_api_key.txt
.hunter_api_key.txt
.getprospect_api_key.txt
.tomba_api_key.txt      (needs BOTH a ta_... key and a ts_... secret in the file)
.minelead_api_key.txt
```

Set `EMAIL_FINDER_KEY_DIR` to point at that folder, or place it as an
`Api Key/` subfolder next to the script itself.

```python
from find_work_email import find_work_email
result = find_work_email("Jane", "Doe", company="Acme Corp", domain="acme.com")
```

Each provider's free tier and confirmed endpoint (as of the date this was
built) is documented in the script's `MONTHLY_LIMITS` dict and the
`_try_*` functions. Combined free-tier ceiling across all five: 249/month
(100 + 50 + 50 + 25 + 24), self-tracked locally per calendar month —
independent of whatever credit dashboard each provider shows you.

Note that MineLead's `/find` endpoint never marks a result "verified" —
it only returns a 0-100 quality score. `find_work_email()` reports a
MineLead hit as `status: "unverified"`, and the research workflow (see
`docs/claude-research-workflow.md`) rejects unverified addresses under the
same rule it applies to every other provider. MineLead is still in the
cascade as one more shot before falling through to "not found," it just
won't ever produce a `READY` candidate on its own under that policy.

Three more providers were evaluated and are NOT wired into the cascade:

- **Lusha** — auth works, but its Person API is a search-and-reveal
  workflow (search their DB for a `contactId`, then reveal that contact),
  not a plain name+domain finder. Would need a different integration
  shape than the rest of the cascade.
- **Kendo** — API key was consistently rejected (`403 invalid API key`)
  across every documented endpoint/auth variant; their own interactive API
  docs page also points at an unconfigured demo spec, suggesting the
  API surface itself is unmaintained. Not usable as of this writing.
- **ZeroBounce** — it's an email *verifier* (confirms an address you
  already have), not a finder — wrong shape for this cascade. Also only
  had 3 free credits on the tested account, too little to matter even if
  repurposed.
- **EmailVerify.io** — key untested; the network environment this was
  built in blocks outbound requests to `api.emailverify.io` at the proxy
  level, unrelated to the key itself. Worth a retry from an unrestricted
  environment before ruling it out.

## Status

Tested against known real email addresses (not yet run against live
campaign candidates). Not wired into any scheduled task — this remains a
manual step in the research workflow until a scheduler invokes it
directly. The outreach side (`codex-outreach-workflow.md`) requires
manual pilot verification — sender address, résumé attachment, tracker
writes — before enabling a standing send schedule. See
`docs/codex-outreach-workflow.md` for the full completion checklist.
