# Private Profile setup

1. Copy `skills/investment-agent/config/private_profile.example.json` locally.
2. Replace every example value with the household's actual data. Keep account
   IDs generic (`member_a`, `member_b`); put human-readable names only in
   `accounts.*.display_name`.
3. Store the complete minified JSON as the GitHub Actions Secret
   `HOS_PRIVATE_PROFILE_JSON`.
4. Store the webhook separately as `DISCORD_WEBHOOK_URL`.

The profile contains goals, balances, holdings, buying power, strategy steps,
completed execution state, and official-IR assessment snapshots. It must never
be committed, pasted into an Issue, printed in CI, or uploaded as an artifact.

For a source to clear an earnings gate, put it under `earnings_ir_sources` with
an exact HTTPS URL, the matching `official_host`, `official_source_verified:
true`, and `source_type: OFFICIAL_IR` or `OFFICIAL_DISCLOSURE`. The endpoint
must return normalized JSON with `period`, `report_date`, `expires_on`,
`guidance_status`, `dividend_status`, and enough operating metrics for the HOS
assessor. PDFs, HTML whose facts cannot be structured, unofficial sources,
stale documents, and fetch errors remain `NEEDS_DATA`; they never unlock a
purchase.

`notification_state` is optional private input for detailed Discord deltas.
HOS does not write it to the repository, Actions cache, artifact, or summary.
An operator may update it in the private profile after a run, or connect an
approved private state store outside this public repository. The workflow's
duplicate guard itself stores only a value-free date/mode/code fingerprint.

Increment the opaque, non-financial `notification_revision` whenever the
profile's holdings, strategy, cash gates, or official facts change during the
same trading day. It invalidates only the value-free duplicate guard; it does
not encode or expose profile contents.

Changing the profile is an operational change: validate it against
`schemas/private_profile.schema.json`, run the dummy-profile tests, then use a
manual workflow dispatch. Missing data is expected to close the purchase gate.

The repository previously contained private runtime/configuration data. Removing
it from HEAD does not erase Git history. Rotate any credential that was tracked
and perform a reviewed history rewrite with repository-owner approval if the
repository's exposure requires it.
