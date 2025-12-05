"""
Model Adapters for different AI providers
Provides unified interface for all models
"""

import os
import time
import json
import re
from abc import ABC, abstractmethod

class BaseModelAdapter(ABC):
    """Base class for all model adapters"""
    
    def __init__(self, model_id, api_key=None):
        self.model_id = model_id
        self.api_key = api_key
        self.client = None
        
    @abstractmethod
    def generate(self, prompt, **kwargs):
        """Generate response from the model"""
        pass
    
    @abstractmethod
    def is_available(self):
        """Check if the model is available (API key configured)"""
        pass
    
    def _log_start(self, operation, **params):
        """Log operation start"""
        print(f"\n{'='*60}")
        print(f"[LLM DEBUG] Starting {operation}")
        for key, value in params.items():
            print(f"  {key}: {value}")
        return time.time()
    
    def _log_success(self, start_time, **metrics):
        """Log successful completion"""
        elapsed = time.time() - start_time
        print(f"[LLM DEBUG] ✅ Operation completed successfully")
        print(f"  Total time: {elapsed:.2f}s")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}\n")
        return elapsed
    
    def _log_error(self, start_time, error):
        """Log error"""
        elapsed = time.time() - start_time
        print(f"[LLM DEBUG] ❌ Operation failed")
        print(f"  Total time: {elapsed:.2f}s")
        print(f"  Error: {str(error)}")
        print(f"{'='*60}\n")


class GeminiAdapter(BaseModelAdapter):
    """Adapter for Google Gemini models"""
    
    def __init__(self, model_id, api_key=None):
        super().__init__(model_id, api_key or os.getenv('GEMINI_API_KEY'))
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"Failed to init Gemini client: {e}")
                self.client = None
    
    def is_available(self):
        return self.client is not None
    
    def generate(self, prompt, use_search=False, **kwargs):
        """Generate using Gemini API"""
        if not self.client:
            raise Exception("Gemini client not initialized")
        
        from google.genai import types
        
        config = {}
        if use_search:
            config['tools'] = [types.Tool(google_search=types.GoogleSearch())]
        
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(**config) if config else None
        )
        
        # Extract usage metadata
        usage = {}
        try:
            if hasattr(response, 'usage_metadata'):
                meta = response.usage_metadata
                usage = {
                    'input_tokens': getattr(meta, 'prompt_token_count', 0),
                    'output_tokens': getattr(meta, 'candidates_token_count', 0)
                }
        except:
            pass
        
        return response.text, usage


class OpenAIAdapter(BaseModelAdapter):
    """Adapter for OpenAI GPT models"""
    
    def __init__(self, model_id, api_key=None):
        super().__init__(model_id, api_key or os.getenv('OPENAI_API_KEY'))
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                print(f"Failed to init OpenAI client: {e}")
                self.client = None
    
    def is_available(self):
        return self.client is not None
    
    def generate(self, prompt, **kwargs):
        """Generate using OpenAI API"""
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        # O1 models use different parameter names
        is_o1 = 'o1' in self.model_id
        
        params = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        if not is_o1:
            params["temperature"] = 0.7
            params["max_tokens"] = kwargs.get('max_tokens', 4096)
        
        response = self.client.chat.completions.create(**params)
        
        usage = {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        }
        
        return response.choices[0].message.content, usage


class AnthropicAdapter(BaseModelAdapter):
    """Adapter for Anthropic Claude models"""
    
    def __init__(self, model_id, api_key=None):
        super().__init__(model_id, api_key or os.getenv('ANTHROPIC_API_KEY'))
        if self.api_key:
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=self.api_key)
            except Exception as e:
                print(f"Failed to init Anthropic client: {e}")
                self.client = None
    
    def is_available(self):
        return self.client is not None
    
    def generate(self, prompt, **kwargs):
        """Generate using Claude API"""
        if not self.client:
            raise Exception("Anthropic client not initialized")
        
        response = self.client.messages.create(
            model=self.model_id,
            max_tokens=kwargs.get('max_tokens', 4096),
            messages=[{"role": "user", "content": prompt}]
        )
        
        usage = {
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens
        }
        
        return response.content[0].text, usage


class QwenAdapter(BaseModelAdapter):
    """Adapter for Alibaba Qwen models"""
    
    def __init__(self, model_id, api_key=None):
        super().__init__(model_id, api_key or os.getenv('QWEN_API_KEY'))
        if self.api_key:
            try:
                from openai import OpenAI
                # Qwen uses OpenAI-compatible API
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
                )
            except Exception as e:
                print(f"Failed to init Qwen client: {e}")
                self.client = None
    
    def is_available(self):
        return self.client is not None
    
    def generate(self, prompt, use_search=False, **kwargs):
        """Generate using Qwen API"""
        if not self.client:
            raise Exception("Qwen client not initialized")
        
        params = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": kwargs.get('max_tokens', 4096)
        }
        
        # Qwen supports web search via tools
        if use_search:
            params["tools"] = [{
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for real-time information"
                }
            }]
        
        response = self.client.chat.completions.create(**params)
        
        usage = {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        }
        
        return response.choices[0].message.content, usage


def get_adapter(model_id):
    """Factory function to get the appropriate adapter"""
    from app.services.model_config import get_model_config
    
    config = get_model_config(model_id)
    if not config:
        raise ValueError(f"Unknown model: {model_id}")
    
    provider = config["provider"]
    
    adapters = {
        "gemini": GeminiAdapter,
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "qwen": QwenAdapter
    }
    
    adapter_class = adapters.get(provider)
    if not adapter_class:
        raise ValueError(f"No adapter for provider: {provider}")
    
    return adapter_class(model_id)

