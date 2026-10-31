# AI orchestration

- One orchestrator only; no multi-agent swarms.
- 11 typed read-only tools with Pydantic argument schemas.
- Bounded execution with timeouts, permissions, validation, error handling, and logs.
- Evidence checking rejects unsupported numbers and strong causal claims.
- Deterministic fallback is always available; external LLMs are optional.
- Evaluation: 20/20 cases passed, 21/21 tool calls successful, citation coverage 1.0.
