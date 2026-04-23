from typing import Dict, List
from openai import OpenAI

class OllamaChat():
    def __init__(self, model: str = "qwen2.5:7b") -> None:
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"
        )
        self.model = model

    def chat(self, prompt: str, history: List[Dict], meta_instruction: str = '') -> (str, List[Dict]):
        history.append({"role": "user", "content": prompt if not meta_instruction else f"{meta_instruction}\n{prompt}"})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=history,
            max_tokens=150,
            temperature=0.1
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        
        return reply, history
