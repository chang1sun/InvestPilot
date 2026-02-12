"""
Model Adapters for different AI providers
Provides unified interface for all models
"""

import os
import time
import json
import re
from abc import ABC, abstractmethod

# Default maximum number of tool call iterations to prevent infinite loops
DEFAULT_MAX_TOOL_ITERATIONS = 10


def _accumulate_usage(total_usage, new_usage):
    """Helper to accumulate token usage from multiple API calls"""
    total_usage['input_tokens'] += new_usage.get('input_tokens', 0)
    total_usage['output_tokens'] += new_usage.get('output_tokens', 0)


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
    
    def generate_with_tools(self, prompt, tool_executor, **kwargs):
        """
        Generate response with function calling (agent mode).
        Subclasses should override this for provider-specific implementation.
        Default: falls back to regular generate() without tools.
        
        Args:
            prompt: The system/user prompt
            tool_executor: AgentToolExecutor instance for executing tool calls
            **kwargs: Additional arguments
            
        Returns:
            Tuple of (text_response, usage_dict)
        """
        # Default fallback: just use regular generate
        return self.generate(prompt, **kwargs)
    
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

    def _openai_compatible_tool_loop(self, messages, tools, tool_executor,
                                     total_usage, extra_params=None,
                                     max_iterations=None):
        """
        Shared function-calling loop for OpenAI-compatible APIs (OpenAI, Qwen).
        Iteratively calls the model, executes tool calls, and appends results.

        Args:
            messages: list of message dicts (mutated in-place)
            tools: list of tool definitions in OpenAI format
            tool_executor: AgentToolExecutor instance
            total_usage: dict {'input_tokens': N, 'output_tokens': N} (mutated)
            extra_params: optional dict of extra params to pass to the API call
            max_iterations: override default iteration limit (for complex tasks)

        Returns:
            Final text response string
        """
        limit = max_iterations or DEFAULT_MAX_TOOL_ITERATIONS
        for iteration in range(limit):
            params = {
                "model": self.model_id,
                "messages": messages,
                "tools": tools,
            }
            if extra_params:
                params.update(extra_params)

            response = self.client.chat.completions.create(**params)

            _accumulate_usage(total_usage, {
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens
            })

            message = response.choices[0].message

            if not message.tool_calls:
                return message.content

            # -- Capture thinking from intermediate steps (tool-calling rounds only) --
            # Source 1: Qwen-style reasoning_content (extended field)
            reasoning = getattr(message, 'reasoning_content', None)
            if reasoning and tool_executor:
                tool_executor.add_thinking(reasoning)

            # Source 2: Standard content text emitted alongside tool calls
            if message.content and tool_executor:
                tool_executor.add_thinking(message.content)

            # Append assistant message with tool calls
            messages.append(message)

            for tool_call in message.tool_calls:
                if tool_call.type != "function":
                    continue
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except Exception:
                    tool_args = {}

                print(f"  [Agent] 🔧 Tool call #{len(tool_executor.tool_calls)+1}: "
                      f"{tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})")

                result_str = tool_executor.execute(tool_name, tool_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str
                })

        # Exhausted iterations -- final call without tools
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages
        )
        _accumulate_usage(total_usage, {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        })
        return response.choices[0].message.content


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
    
    def _extract_gemini_usage(self, response):
        """Extract usage metadata from Gemini response"""
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
        return usage

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
        
        usage = self._extract_gemini_usage(response)
        return response.text, usage

    def generate_with_tools(self, prompt, tool_executor, **kwargs):
        """Generate with function calling using Gemini API"""
        if not self.client:
            raise Exception("Gemini client not initialized")
        
        from google.genai import types
        from app.services.agent_tools import get_gemini_tools
        
        gemini_tools = get_gemini_tools()
        # NOTE: Gemini 3 does NOT allow mixing function_declarations and
        # google_search in the same tools list.  Our own search_market_news
        # tool already wraps Gemini Search, so we don't need GoogleSearch here.
        
        config = types.GenerateContentConfig(tools=gemini_tools)
        
        # Start multi-turn conversation
        contents = [prompt]
        total_usage = {'input_tokens': 0, 'output_tokens': 0}
        
        limit = kwargs.get('max_iterations') or DEFAULT_MAX_TOOL_ITERATIONS
        for iteration in range(limit):
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=config
            )
            
            # Accumulate usage
            usage = self._extract_gemini_usage(response)
            total_usage['input_tokens'] += usage.get('input_tokens', 0)
            total_usage['output_tokens'] += usage.get('output_tokens', 0)
            
            # Check if response contains function calls
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                break
            
            has_function_call = False
            function_response_parts = []
            thinking_parts = []
            
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    thinking_parts.append(part.text)
                if hasattr(part, 'function_call') and part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    
                    print(f"  [Agent] 🔧 Tool call #{len(tool_executor.tool_calls)+1}: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})")
                    
                    # Execute the tool
                    result_str = tool_executor.execute(tool_name, tool_args)
                    
                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result_str}
                        )
                    )
            
            if not has_function_call:
                # No more function calls - we have the final response
                break
            
            # Record model thinking that came alongside tool calls
            if thinking_parts:
                tool_executor.add_thinking("\n".join(thinking_parts))
            
            # Add assistant's response and tool results to conversation
            contents.append(candidate.content)
            contents.append(types.Content(parts=function_response_parts, role="user"))
                    
        # Extract final text response
        try:
            text = response.text
        except Exception:
            # If .text fails, try to extract from parts
            text = ""
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text += part.text
        
        return text, total_usage


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
    
    def generate(self, prompt, use_search=False, **kwargs):
        """Generate using OpenAI API"""
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        params = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
        }

        if use_search:
            params["tools"] = [ { "type": "web_search" } ]
        
        response = self.client.chat.completions.create(**params)
        
        usage = {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        }
        
        return response.choices[0].message.content, usage

    def generate_with_tools(self, prompt, tool_executor, **kwargs):
        """Generate with function calling using OpenAI API"""
        if not self.client:
            raise Exception("OpenAI client not initialized")
        
        from app.services.agent_tools import get_openai_tools
        
        tools = get_openai_tools()
        tools.append({"type": "web_search"})
        
        messages = [{"role": "user", "content": prompt}]
        total_usage = {'input_tokens': 0, 'output_tokens': 0}
        
        text = self._openai_compatible_tool_loop(
            messages, tools, tool_executor, total_usage,
            max_iterations=kwargs.get('max_iterations')
        )
        return text, total_usage


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
            max_tokens=kwargs.get('max_tokens', 8192),
            messages=[{"role": "user", "content": prompt}]
        )
        
        usage = {
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens
        }
        
        return response.content[0].text, usage

    def generate_with_tools(self, prompt, tool_executor, **kwargs):
        """Generate with tool use using Anthropic API"""
        if not self.client:
            raise Exception("Anthropic client not initialized")
        
        from app.services.agent_tools import get_anthropic_tools
        
        tools = get_anthropic_tools()
        messages = [{"role": "user", "content": prompt}]
        total_usage = {'input_tokens': 0, 'output_tokens': 0}
        
        limit = kwargs.get('max_iterations') or DEFAULT_MAX_TOOL_ITERATIONS
        for iteration in range(limit):
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=kwargs.get('max_tokens', 8192),
                messages=messages,
                tools=tools
            )
            
            # Accumulate usage
            total_usage['input_tokens'] += response.usage.input_tokens
            total_usage['output_tokens'] += response.usage.output_tokens
            
            # Check if response contains tool use
            has_tool_use = False
            tool_results = []
            text_parts = []
            
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    has_tool_use = True
                    tool_name = block.name
                    tool_args = block.input or {}
                    tool_use_id = block.id
                    
                    print(f"  [Agent] 🔧 Tool call #{len(tool_executor.tool_calls)+1}: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:100]})")
                    
                    result_str = tool_executor.execute(tool_name, tool_args)
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_str
                    })
            
            if not has_tool_use or response.stop_reason == "end_turn":
                # No more tool calls - return the text
                return "\n".join(text_parts) if text_parts else "", total_usage

            # Capture Claude's thinking text emitted alongside tool calls (intermediate steps only)
            if text_parts:
                tool_executor.add_thinking("\n".join(text_parts))
            
            # Add assistant response and tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
                    
        # If we exhausted iterations, do a final call without tools
        response = self.client.messages.create(
            model=self.model_id,
            max_tokens=kwargs.get('max_tokens', 8192),
            messages=messages
        )
        total_usage['input_tokens'] += response.usage.input_tokens
        total_usage['output_tokens'] += response.usage.output_tokens
        
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text
        
        return text, total_usage


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
        }
        
        # 通过 extra_body 兼容OpenAI API
        if use_search:
            params["extra_body"] = {
                "enable_thinking": True,
                "enable_search": True,
                "search_options": {
                    "forced_search": True,
                    "search_strategy": "max"
                }
            }
        
        response = self.client.chat.completions.create(**params)
        
        usage = {
            'input_tokens': response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens
        }
        
        return response.choices[0].message.content, usage

    def generate_with_tools(self, prompt, tool_executor, **kwargs):
        """Generate with function calling using Qwen API (OpenAI-compatible)"""
        if not self.client:
            raise Exception("Qwen client not initialized")
        
        from app.services.agent_tools import get_qwen_tools
        
        tools = get_qwen_tools()
        messages = [{"role": "user", "content": prompt}]
        total_usage = {'input_tokens': 0, 'output_tokens': 0}
        
        text = self._openai_compatible_tool_loop(
            messages, tools, tool_executor, total_usage,
            extra_params={
                "extra_body": {
                    "enable_thinking": True,
                    "enable_search": True,
                    "search_options": {
                        "forced_search": True,
                        "search_strategy": "pro"
                    }
                }
            },
            max_iterations=kwargs.get('max_iterations')
        )
        return text, total_usage


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

