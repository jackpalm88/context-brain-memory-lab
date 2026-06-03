import os
import logging

logger = logging.getLogger(__name__)

VALID_LLM_PROVIDERS   = {"none", "anthropic", "openai", "openrouter", "custom_http", "local"}
VALID_EMBED_PROVIDERS = {"none", "openai", "custom_http", "local"}


class ProviderConfig:
    """Read provider configuration from environment. Never raises. Never logs key values."""

    def __init__(self) -> None:
        self.llm_provider        = os.environ.get("LLM_PROVIDER", "none").lower()
        self.llm_model           = os.environ.get("LLM_MODEL", "")
        self.embedding_provider  = os.environ.get("EMBEDDING_PROVIDER", "none").lower()
        self.embedding_model     = os.environ.get("EMBEDDING_MODEL", "")
        self.anthropic_api_key   = os.environ.get("ANTHROPIC_API_KEY", "")
        self.openai_api_key      = os.environ.get("OPENAI_API_KEY", "")
        self.openrouter_api_key  = os.environ.get("OPENROUTER_API_KEY", "")
        self.custom_llm_base_url = os.environ.get("CUSTOM_LLM_BASE_URL", "")
        self.custom_emb_base_url = os.environ.get("CUSTOM_EMBEDDING_BASE_URL", "")

        if self.llm_provider not in VALID_LLM_PROVIDERS:
            logger.warning(
                "[providers] Unknown LLM_PROVIDER=%r — falling back to 'none'",
                self.llm_provider,
            )
            self.llm_provider = "none"

        if self.embedding_provider not in VALID_EMBED_PROVIDERS:
            logger.warning(
                "[providers] Unknown EMBEDDING_PROVIDER=%r — falling back to 'none'",
                self.embedding_provider,
            )
            self.embedding_provider = "none"

    @property
    def llm_is_active(self) -> bool:
        return self.llm_provider != "none"

    @property
    def embedding_is_active(self) -> bool:
        return self.embedding_provider != "none"

    def __repr__(self) -> str:
        return (
            f"ProviderConfig(llm={self.llm_provider!r}, "
            f"embedding={self.embedding_provider!r}, "
            f"llm_key_set={bool(self.anthropic_api_key or self.openai_api_key or self.openrouter_api_key)}, "
            f"emb_key_set={bool(self.openai_api_key)})"
        )
