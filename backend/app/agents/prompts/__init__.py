"""Every LLM prompt the factory sends, in one place.

One module per agent. Each prompt is a constant or a small function that fills in the facts.
Agents import from here; nothing else in the codebase should hold prompt text.

Note: the LLM record/replay cache keys on the exact prompt text, so editing a prompt here
invalidates its cached responses in demo/llm_cache (run `make record-llm` again).
"""
