"""
Step 1: First contact with a local model.

What this does:
  Sends one conversation to Ollama (running on your Mac) and prints the reply
  word by word as it is generated (streaming).

Run:
  python examples/01_hello.py
"""
import time
import ollama

MODEL = "qwen3.5:9b"  # change this to try another model, e.g. "gemma4:e4b"

# The conversation. The model has no memory, so we always send the full list.
messages = [
    {"role": "system", "content": "You are a concise assistant."},       # agent's instructions
    {"role": "user", "content": "In one sentence, what is an AI agent?"},  # the human's message
]

print(f"Asking {MODEL}... (first run loads the model into RAM, so it can take a bit)\n")
start = time.time()

stream = ollama.chat(
    model=MODEL,
    messages=messages,
    stream=True,   # give us the reply piece by piece instead of all at the end
    think=False,   # skip the hidden "thinking" step for reasoning models like Qwen
)

for chunk in stream:
    print(chunk.message.content, end="", flush=True)  # flush = show it immediately

print(f"\n\n[done in {time.time() - start:.1f}s]")
