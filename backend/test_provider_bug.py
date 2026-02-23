"""
Quick diagnostic test for provider speech bug
Run this to see exactly where it fails
"""

import asyncio
import json
from agents.service_agent import get_or_create_agent

async def test_provider_speech():
    print("\n" + "="*80)
    print("TESTING PROVIDER SPEECH PATH")
    print("="*80)
    
    session_id = "test-session-123"
    
    # Step 1: Create agent
    print("\n[1] Creating agent...")
    agent = get_or_create_agent(session_id, lang="hi")
    print("✓ Agent created")
    
    # Step 2: First turn (should show button)
    print("\n[2] First turn - user signs 'hungry'...")
    try:
        response = await agent.get_response(
            user_input="hungry",
            detected_intent="food_order",
            detected_details={},
            lang="hi",
            session_id=session_id
        )
        print(f"✓ Response: {response[0][:100]}...")
        print(f"✓ Signal: {response[4]}")
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 3: Click button (should greet provider)
    print("\n[3] Click button - greet provider...")
    try:
        response = await agent.get_response(
            user_input="",
            detected_intent="voice_chat",
            detected_details={},
            lang="hi",
            session_id=session_id,
            action="speak_to_waiter"
        )
        print(f"✓ Response: {response[0][:100]}...")
        print(f"✓ Signal: {response[4]}")
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 4: Provider speaks (THIS IS WHERE IT LIKELY FAILS)
    print("\n[4] Provider speaks 'we have idli'...")
    print("    This is where the bug should appear...")
    try:
        response = await agent.get_response(
            user_input="",
            detected_intent="voice_chat",
            detected_details={},
            lang="hi",
            session_id=session_id,
            waiter_speech="we have idli"
        )
        print(f"✓ Response received!")
        print(f"✓ bot_response: {response[0][:200]}")
        print(f"✓ status: {response[1]}")
        print(f"✓ food_options: {response[2]}")
        print(f"✓ waiter_lang: {response[3]}")
        print(f"✓ signal: {response[4]}")
        
        # Parse the response
        if "PROVIDER_REPLY:" in response[0]:
            pr = response[0].split("PROVIDER_REPLY:")[1].split("USER_SUMMARY:")[0].strip()
            us = response[0].split("USER_SUMMARY:")[1].strip()
            print(f"\n✓ PROVIDER_REPLY: {pr}")
            print(f"✓ USER_SUMMARY: {us}")
        
    except asyncio.TimeoutError:
        print(f"✗ TIMEOUT: Agent took too long to respond (>20 seconds)")
        print(f"   This means the LLM is still blocking!")
    except Exception as e:
        print(f"✗ FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n" + "="*80)
    print("TEST COMPLETE - If you see this, the bug is FIXED!")
    print("="*80)

if __name__ == "__main__":
    print("Starting provider speech diagnostic test...")
    asyncio.run(test_provider_speech())
