"""Local LLM layer (Phase 4).

interface.py defines the chat-completion seam (LLMClient); local_llama.py is the
llama.cpp implementation; prompt.py owns evidence shaping, the prompt text, and
the cache key; template.py is the deterministic non-LLM fallback that lives
ABOVE the seam (selected by ExplanationService, not behind LLMClient).
"""
