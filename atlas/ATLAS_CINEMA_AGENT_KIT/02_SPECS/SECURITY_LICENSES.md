# Operational security and copyright controls

LLM plans are data, not privileged executable Python. Validate against an allowlisted scene DSL and run generated Blender scripts only in isolated, unprivileged containers with quotas, no host mounting, network blocked where feasible, access to signed/downloaded assets only and no secret environment variables. Imported `.blend`, addons, python files, archives and textures are untrusted; quarantine, scan, checksum and disable Blender autorun scripts. Protect against zip slip, decompression bombs and crafted payloads. Secrets only on trusted control-plane tasks; worker secrets are short-lived and scoped.

Cloud API keys in secret manager; no `.env` committing. Scope R2 tokens to least privilege. Per-user rate limits, job spend ceiling, asset entitlement checks and audit logs. Separate authentication from authorization. Preview/output object URLs are short-lived.

Keep licenses and provenance on every asset and derivative. CC0 sources may support commercial video; paid marketplace models are often licensed for incorporation into rendered works, not resale or broad source-file distribution. Verify every specific asset's terms. Do not include copyrighted binary packs or paid add-ons in this ZIP. Provide manual import/entitlement checks. Record soundtrack and voice rights too.
