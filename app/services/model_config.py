"""
Multi-Model Configuration for AI Quant Agent
Supports: Gemini, GPT, Claude, Grok, Qwen
"""

MODEL_REGISTRY = {
    # ===== Google Gemini =====
    "gemini-3-pro-preview": {
        "provider": "gemini",
        "display_name": "Gemini 3 Pro (Preview)",
        "api_key_env": "GEMINI_API_KEY",
        "supports_search": True,
        "max_tokens": 2097152,  # 2M上下文
        "cost_tier": "high"
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "display_name": "Gemini 2.5 Flash",
        "api_key_env": "GEMINI_API_KEY",
        "supports_search": True,
        "max_tokens": 1048576,  # 1M上下文
        "cost_tier": "low"
    },
    
    # ===== OpenAI GPT =====
    "gpt-5.1": {
        "provider": "openai",
        "display_name": "GPT-5.1",
        "api_key_env": "OPENAI_API_KEY",
        "supports_search": False,
        "max_tokens": 32768,
        "cost_tier": "premium"
    },
    "gpt-5-mini": {
        "provider": "openai",
        "display_name": "GPT-5 Mini",
        "api_key_env": "OPENAI_API_KEY",
        "supports_search": False,
        "max_tokens": 16384,
        "cost_tier": "medium"
    },
    "gpt-5-nano": {
        "provider": "openai",
        "display_name": "GPT-5 Nano",
        "api_key_env": "OPENAI_API_KEY",
        "supports_search": False,
        "max_tokens": 8192,
        "cost_tier": "low"
    },
    
    # ===== Anthropic Claude =====
    "claude-sonnet-4-5": {
        "provider": "anthropic",
        "display_name": "Claude Sonnet 4.5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_search": False,
        "max_tokens": 200000,  # 200K上下文
        "cost_tier": "high"
    },
    "claude-haiku-4-5": {
        "provider": "anthropic",
        "display_name": "Claude Haiku 4.5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_search": False,
        "max_tokens": 200000,  # 200K上下文
        "cost_tier": "low"
    },
    "claude-opus-4-5": {
        "provider": "anthropic",
        "display_name": "Claude Opus 4.5",
        "api_key_env": "ANTHROPIC_API_KEY",
        "supports_search": False,
        "max_tokens": 200000,  # 200K上下文
        "cost_tier": "premium"
    },
    
    # ===== Alibaba Qwen =====
    "qwen3-max": {
        "provider": "qwen",
        "display_name": "Qwen3 Max",
        "api_key_env": "QWEN_API_KEY",
        "supports_search": True,
        "max_tokens": 262144,  # 256K上下文
        "cost_tier": "high"
    },
    "qwen-plus": {
        "provider": "qwen",
        "display_name": "Qwen Plus",
        "api_key_env": "QWEN_API_KEY",
        "supports_search": True,
        "max_tokens": 131072,  # 128K上下文
        "cost_tier": "medium"
    },
    "qwen-flash": {
        "provider": "qwen",
        "display_name": "Qwen Flash",
        "api_key_env": "QWEN_API_KEY",
        "supports_search": False,
        "max_tokens": 32768,
        "cost_tier": "low"
    },
    
    # ===== Local Strategy =====
    "local-strategy": {
        "provider": "local",
        "display_name": "Local Algo (MA+RSI)",
        "api_key_env": None,
        "supports_search": False,
        "max_tokens": 0,
        "cost_tier": "free"
    }
}

# Provider Base URLs
PROVIDER_URLS = {
    "gemini": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "qwen": "https://dashscope.aliyuncs.com/api/v1"
}

def get_model_config(model_id):
    """Get configuration for a specific model"""
    return MODEL_REGISTRY.get(model_id)

def get_available_models():
    """Get all available models grouped by provider"""
    grouped = {}
    for model_id, config in MODEL_REGISTRY.items():
        provider = config["provider"]
        if provider not in grouped:
            grouped[provider] = []
        grouped[provider].append({
            "id": model_id,
            "name": config["display_name"],
            "cost_tier": config["cost_tier"],
            "supports_search": config["supports_search"]
        })
    return grouped

def get_models_for_frontend():
    """Get models formatted for frontend display"""
    models = []
    for model_id, config in MODEL_REGISTRY.items():
        models.append({
            "id": model_id,
            "name": config["display_name"],
            "provider": config["provider"],
            "supports_search": config["supports_search"]
        })
    return models

