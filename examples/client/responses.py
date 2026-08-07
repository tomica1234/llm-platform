import os

import httpx

key = os.environ["LOCAL_LLM_GATEWAY_API_KEY"]
response = httpx.post(
    "http://127.0.0.1:8000/v1/responses",
    headers={"Authorization": f"Bearer {key}"},
    json={"model": "auto", "input": "Explain this repository briefly."},
    timeout=300,
)
response.raise_for_status()
print(response.json())
