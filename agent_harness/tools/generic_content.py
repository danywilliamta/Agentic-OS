"""
Generic Content Generation Tools - Work with any LLM provider.
"""

from typing import Dict, Any, Optional
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="content")
def generic_content_generator(
    llm_provider: str,
    api_key: str,
    model: str,
    prompt: str,
    max_tokens: int = 1000,
    temperature: float = 0.7,
    system_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generic content generator - works with Anthropic, OpenAI, etc.

    Args:
        llm_provider: Provider name ('anthropic', 'openai', 'cohere')
        api_key: Provider API key
        model: Model name
        prompt: Generation prompt
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature
        system_prompt: Optional system prompt

    Returns:
        Dict with generated content
    """
    try:
        if llm_provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)

            messages = [{"role": "user", "content": prompt}]
            if system_prompt:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=messages
                )
            else:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages
                )

            return {
                "success": True,
                "content": response.content[0].text,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                },
                "error": None
            }

        elif llm_provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key)

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )

            return {
                "success": True,
                "content": response.choices[0].message.content,
                "usage": {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens
                },
                "error": None
            }

        else:
            return {
                "success": False,
                "content": None,
                "error": f"Unsupported LLM provider: {llm_provider}"
            }

    except Exception as e:
        return {
            "success": False,
            "content": None,
            "error": str(e)
        }