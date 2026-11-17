# NewsFlow fact-check hardening

The Groq/Tavily fact-check request now uses JSON-object response mode and explicitly disables model tool calls. The local validator remains authoritative: every material claim must be supported by at least one cited source independent of the original publisher. Unsupported stories remain blocked. YouTube review staging remains PRIVATE-only.
