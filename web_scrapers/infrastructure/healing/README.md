# Self-healing selectors

When a carrier changes their portal UI and a selector stops matching, the
healing wrapper recovers the job in-flight instead of failing it: capture
evidence → check known overrides → classify (CAPTCHA/bot pages are never
healed) → ask Claude for a replacement locator → validate it live → persist it
so future runs use it without any AI call.

## Safety model — why this can't hurt the current system

- **Off by default.** `HEALING_ENABLED` unset/false → `build_browser_wrapper`
  returns the plain `PlaywrightWrapper`; no healing code runs at all.
- **Single hook.** All action methods route through `PlaywrightWrapper._wait_for`,
  whose base implementation is byte-identical to the old inline waits. Healing
  lives entirely in the `HealingPlaywrightWrapper` subclass override.
- **Failure-neutral.** Every healing-path error (evidence capture, API down,
  budget hit, bad proposal) re-raises the *original* selector timeout — the job
  fails exactly as it does today, plus evidence in `downloads/job_{id}/`.
- **Boolean probes untouched.** `find_element_by_xpath` / `is_element_visible`
  keep returning False on absence — absence checks are sometimes intentional.

## Guardrails

- Never heals auth/MFA/CAPTCHA steps (caller module/method + URL deny patterns).
- CAPTCHA pages raise `CaptchaBlockedError`, hard bot blocks raise
  `BotDetectedError` — typed, legible failures for the solver stack / session
  hygiene work; the AI never pokes challenge pages.
- Healed candidate must match exactly one element and must not be a destructive
  control (delete / cancel service / purchase / pay ...).
- Budgets: `HEALING_MAX_HEALS_PER_JOB` (3), `HEALING_DAILY_MAX_CALLS` (25,
  global cost cap ≈ $1–2/day worst case on Sonnet), `HEALING_STEP_BUDGET_SECONDS`
  (120, protects time-sensitive sessions).
- Privacy: DOM sent to the API has scripts stripped and all input values
  blanked. Screenshots can contain account data — disable per-env with
  `HEALING_SCREENSHOTS=false` for DOM-only healing.

## Rollout

1. Dev box: `HEALING_ENABLED=true`, optionally `HEALING_CARRIERS=bell` to gate
   per carrier. `ANTHROPIC_API_KEY` must be set (slot already in SSM).
2. Verify with the replay harness (no real carrier needed):
   `poetry run python scripts/healing_replay.py`
3. Watch logs for `HEALED selector` / `Override applied` lines and review
   `healing_overrides.json` — each entry is a proposed permanent fix for the
   inline selector it shadows. Port accepted overrides into the strategy code
   via normal PRs, then delete the entry.

## Follow-ups (deliberately out of v1)

- Automatic PR generation from new overrides (needs a repo-scoped token on the executor).
- Routing `captcha_blocked` to the solver stack mid-flow (solvers currently live
  inside auth strategies; typed errors make the failure legible today).
- Healing for `expect_download_and_click` / `click_and_switch_to_new_tab`
  (no pre-wait today; adding one changes timing behavior — needs its own pass).
- Nightly login+navigate smoke probe per carrier; AI morning digest; drift
  dashboard (override use_count already collects the data).
