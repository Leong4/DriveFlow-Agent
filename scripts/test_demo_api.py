import httpx

try:
    resp = httpx.post("http://127.0.0.1:8080/demo/run", json={"query": "我想去白云山，路上先找一家麦当劳"}, timeout=30.0)
    print("STATUS:", resp.status_code)
    print("RESPONSE:", resp.text)
except Exception as e:
    print(f"Error: {e}")
