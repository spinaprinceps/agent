import asyncio
import json
import websockets

async def run_test():
    uri = "ws://localhost:8080/ws/session-test"
    print(f"Connecting to {uri}")
    try:
        async with websockets.connect(uri) as ws:
            print("Connected. Sending provider speech payload...")
            payload = {"text": "we have idli", "type": "text", "lang": "hi", "session_id": "session-test"}
            await ws.send(json.dumps(payload))
            print("Payload sent. Waiting for response... (5s timeout)")
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                print("Received from server:", msg)
            except asyncio.TimeoutError:
                print("No response within 10s")
    except Exception as e:
        print("Connection error:", e)

if __name__ == '__main__':
    asyncio.run(run_test())
