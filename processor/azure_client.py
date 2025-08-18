# processor/azure_client.py
import requests
import json
import asyncio
from typing import Dict, List, Optional

class AzureOpenAIClient:
    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key
        }
    
    async def chat_completion_create(self, 
                                   model: str,
                                   messages: List[Dict[str, str]], 
                                   max_tokens: int = 150,
                                   seed: Optional[int] = None,
                                   **extra_payload) -> object:
        payload = {
            "messages": messages,
            "max_completion_tokens": max_tokens
        }
        if seed is not None:
            payload["seed"] = seed
        if extra_payload:
            payload.update(extra_payload)
        
        def make_request():
            response = requests.post(
                self.endpoint,
                headers=self.headers,
                data=json.dumps(payload),
                timeout=60
            )
            response.raise_for_status()
            return response.json()
        
        result = await asyncio.to_thread(make_request)
        
        class Message:
            def __init__(self, content): self.content = content
        class Choice:
            def __init__(self, message): self.message = message
        class ChatCompletion:
            def __init__(self, choices): self.choices = choices
        
        content = result['choices'][0]['message'].get('content', '')
        return ChatCompletion([Choice(Message(content))])

class ChatCompletions:
    def __init__(self, client): self.client = client
    async def create(self, **kwargs): return await self.client.chat_completion_create(**kwargs)

class Chat:
    def __init__(self, client): self.completions = ChatCompletions(client)

class AzureOpenAI:
    def __init__(self, endpoint: str, api_key: str):
        self.client = AzureOpenAIClient(endpoint, api_key)
        self.chat = Chat(self.client)