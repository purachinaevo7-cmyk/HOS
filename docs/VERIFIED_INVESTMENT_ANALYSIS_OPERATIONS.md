# Verified Investment Analysis Operations

Recommended order:

1. Run `fact_pack_only=true`, `fact_mode=cached_only`.
2. Run `fact_pack_only=true`, `fact_mode=network_verified`, `enable_network_facts=true`.
3. Run `analysis_mode=verified_lite` with Gemini.
4. Use `analysis_mode=full_5_agent` only for comparison.

Network facts are allowed only when both `HOS_FACT_MODE=network_verified` and `HOS_ENABLE_NETWORK_FACTS=true`. Provider errors, source map, cache status, Discord text, and Investment Commander JSON are stored in run artifacts. Secrets are not included in provider logs.
