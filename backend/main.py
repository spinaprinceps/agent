import os
import io
import json
import base64
import asyncio
from langdetect import detect, DetectorFactory

# Force consistent detection
DetectorFactory.seed = 0
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from agents.service_agent import get_or_create_agent, GraphAgent
from gemini_live_client import GeminiLiveClient, create_tools_declaration, create_system_prompt
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="ISL Service MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Vertex AI (for vision model only)
vertexai.init(
    project=os.getenv("GOOGLE_PROJECT_ID"),
    location="us-central1"
)

# Vision model for ISL video analysis
gemini_model = GenerativeModel("gemini-2.0-flash-001")

# ---------------------------------------------------------------------------
# TTS Helper — Google Cloud Text-to-Speech (female voice)
# ---------------------------------------------------------------------------

def _get_tts_voice(lang: str) -> dict:
    """Return the best female voice params for the given lang code."""
    voice_map = {
        "hi": {"language_code": "hi-IN", "name": "hi-IN-Wavenet-A"},   # female
        "en": {"language_code": "en-US", "name": "en-US-Wavenet-C"},   # female (US English)
        "kn": {"language_code": "kn-IN", "name": "kn-IN-Wavenet-A"},   # female
        "ta": {"language_code": "ta-IN", "name": "ta-IN-Wavenet-A"},   # female
    }
    return voice_map.get(lang, voice_map["en"])  # Default to English female


def generate_tts(text: str, lang: str = "hi") -> str | None:
    """
    Generate speech using Google Cloud TTS with a female voice.
    Returns base64-encoded MP3 string, or None on failure.
    """
    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        voice_params = _get_tts_voice(lang)

        synthesis_input = texttospeech.SynthesisInput(text=text[:4096])
        voice = texttospeech.VoiceSelectionParams(
            language_code=voice_params["language_code"],
            name=voice_params["name"],
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        return base64.b64encode(response.audio_content).decode("utf-8")
    except Exception as e:
        err_msg = str(e)
        if "SERVICE_DISABLED" in err_msg or "403" in err_msg:
            print("[TTS] Notice: Text-to-Speech API is disabled in GCP. Falling back to browser TTS.")
        else:
            print(f"[TTS] Error generating audio: {err_msg}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re
from langdetect import detect, DetectorFactory

# Ensure consistent results
DetectorFactory.seed = 0

def _detect_waiter_lang(text: str) -> str:
    """Detect language and map to supported codes (hi, en, ta, kn)."""
    if not text or len(text.strip()) < 3:
        return "en"
    try:
        lang_code = detect(text)
        # Map common codes
        mapping = {"hi": "hi", "en": "en", "ta": "ta", "kn": "kn"}
        return mapping.get(lang_code, "en")
    except:
        return "en"

def _extract_food_tags(text: str) -> list:
    """Simple extraction of food words for placeholder images."""
    # List of common food items to match
    keywords = ["idli", "tea", "coffee", "chai", "vada", "dosa", "samosa", "biryani", "pizza", "burger", "roti"]
    found = []
    lower_text = text.lower()
    for k in keywords:
        if k in lower_text:
            found.append(k)
    return found

def _build_response(bot_response: str, status: str, food_options: list, waiter_lang: str, agent_signal: str = None) -> dict:
    """Build a unified response payload with optional TTS audio."""
    clean_text = bot_response.replace("WORK_DONE", "").strip()

    # Extract provider reply and user summary
    provider_reply = ""
    user_summary = ""
    
    if "PROVIDER_REPLY:" in clean_text and "USER_SUMMARY:" in clean_text:
        parts = clean_text.split("USER_SUMMARY:")
        provider_part = parts[0].replace("PROVIDER_REPLY:", "").strip()
        summary_part = parts[1].strip()
        
        provider_reply = provider_part
        user_summary = summary_part
    else:
        # Fallback: if not structured, assume it's for the user
        user_summary = clean_text
        provider_reply = clean_text

    # Build payload
    payload: dict = {
        "bot_response": user_summary,  # User sees this (English summary)
        "bot_response_to_provider": provider_reply,  # Provider hears this (in their language)
        "user_summary": user_summary,
        "status": status,
        "waiter_lang": waiter_lang,
    }

    # Handle signals
    if agent_signal:
        payload["signal"] = agent_signal
        
        # Handle specific signals
        if agent_signal == "SHOW_PROVIDER_BUTTON" or agent_signal == "SHOW_WAITER_BUTTON":
            payload["signal"] = "SHOW_WAITER_BUTTON"  # Frontend uses this
            print(f"[SIGNAL] Mapped SHOW_PROVIDER_BUTTON to SHOW_WAITER_BUTTON")
        elif agent_signal == "SHOW_PLACEHOLDER_IMAGES":
            payload["items"] = food_options
            print(f"[SIGNAL] SHOW_PLACEHOLDER_IMAGES with {len(food_options)} items")
        elif agent_signal == "ORDER_DONE":
            payload["order_success"] = True
            status = "done"
            payload["status"] = "done"
            print(f"[SIGNAL] ORDER_DONE - order completed")
        elif agent_signal == "WAITER_ACTIVE":
            print(f"[SIGNAL] WAITER_ACTIVE - provider mode activated")
    
    # Legacy food_options support
    if food_options and not agent_signal:
        payload["food_options"] = food_options
        payload["items"] = food_options
        payload["signal"] = "SHOW_PLACEHOLDER_IMAGES"

    # Generate TTS audio for provider side in their language (only if not [NONE])
    # Agent speaks TO provider with female voice in provider's language
    if provider_reply and provider_reply.strip() and provider_reply != "[NONE]":
        print(f"[TTS] Generating audio for provider in {waiter_lang}: {provider_reply[:50]}...")
        voice_audio = generate_tts(provider_reply, waiter_lang)
        if voice_audio:
            payload["voice_audio"] = voice_audio
            print(f"[TTS] Audio generated successfully ({len(voice_audio)} chars)")
        else:
            print(f"[TTS] Audio generation failed, will use browser TTS fallback")

    return payload


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/upload-isl-video")
async def upload_isl_video(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    lang: str = Form("hi")
):
    print(f"[UPLOAD] session: {session_id}, lang: {lang}")
    video_bytes = await file.read()

    if not video_bytes:
        return {"error": "Empty video file received"}

    prompt = (
        "Analyze this short video of Indian Sign Language. "
        "Quickly transcribe the sign to English text (1-3 words) and detect the intent. "
        "Intent options: food_order (if signing about food/eating/hungry), book_transport, book_appointment, or general. "
        "Return ONLY a valid JSON object: {\"text\": \"short description\", \"intent\": \"food_order\", \"details\": {}}"
    )

    video_part = Part.from_data(data=video_bytes, mime_type="video/webm")

    try:
        print(f"[VISION] Sending video to Gemini 2.0 Flash (size: {len(video_bytes)} bytes)")
        response = gemini_model.generate_content(
            [prompt, video_part],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.95,
            ),
            request_options={"timeout": 30}
        )
        print(f"[VISION] Gemini response received")

        analysis = json.loads(response.text)
        print(f"[DEBUG] [VISION] Analysis: {analysis}")

        agent = get_or_create_agent(session_id, lang=lang)
        print(f"[DEBUG] [SESSION] Before agent: {get_or_create_agent(session_id, lang)}")
        bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
            user_input=analysis["text"],
            detected_intent=analysis["intent"],
            detected_details=analysis.get("details", {}),
            lang=lang,
            session_id=session_id,
        )
        print(f"[DEBUG] [AGENT] Response: {bot_response}, Signal: {signal}")

        payload = _build_response(bot_response, status, food_options, waiter_lang, signal)
        payload["user_text"] = analysis["text"]
        payload["intent"] = analysis["intent"]
        return payload

    except Exception as e:
        print(f"[ERROR] processing video: {e}")
        import traceback; traceback.print_exc()

        agent = get_or_create_agent(session_id, lang=lang)
        bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
            user_input="I want to order food",
            detected_intent="food_order",
            detected_details={},
            lang=lang,
            session_id=session_id,
        )

        payload = _build_response(bot_response, status, food_options, waiter_lang, signal)
        payload["user_text"] = "Sign not recognized - falling back"
        payload["intent"] = "food_order"
        return payload


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"\n{'='*100}")
    print(f"[WS] ✓ CLIENT CONNECTED: {session_id}")
    print(f"{'='*100}")

    agent = get_or_create_agent(session_id, lang="hi")
    print(f"[WS] ✓ Agent created/retrieved")

    message_count = 0
    while True:
        try:
            message_count += 1
            print(f"\n[WS] ▶ Waiting for message #{message_count}...")
            raw_data = await websocket.receive_text()
            print(f"[WS] ◀ Message #{message_count} received ({len(raw_data)} bytes)")
            print(f"[WS] Raw data: {raw_data[:200]}...")
            payload = json.loads(raw_data)
            print(f"[WS] ✓ JSON parsed successfully")

            # Extract payload fields
            waiter_speech = payload.get("text", "")
            action = payload.get("action")
            lang = payload.get("lang", "hi")
            selected_item = payload.get("item", "")

            # Variables to hold response
            bot_response = ""
            status = "pending"
            food_options = []
            waiter_lang = "hi"
            signal = "NONE"

            # Determine processing mode
            try:
                if action == "speak_to_waiter":
                    print("[WS] Action: speak_to_waiter")
                    bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
                        user_input="",
                        detected_intent="voice_chat",
                        detected_details={},
                        lang=lang,
                        session_id=session_id,
                        action="speak_to_waiter",
                    )

                elif action == "user_selection" and selected_item:
                    print(f"[WS] Action: user_selection - item: {selected_item}")
                    bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
                        user_input="",
                        detected_intent="voice_chat",
                        detected_details={},
                        lang=lang,
                        session_id=session_id,
                        action="user_selection",
                        selected_item=selected_item,
                    )

                elif waiter_speech:
                    print("\n" + "#"*100)
                    print(f"[WS] 🎤 PROVIDER SPOKE: '{waiter_speech}'")
                    print(f"[WS] Speech length: {len(waiter_speech)} chars")
                    print("#"*100)
                    try:
                        print(f"[WS] → Detecting language...")
                        detected_lang = detect(waiter_speech) if len(waiter_speech) >= 3 else "en"
                        print(f"[WS] ✓ Language detected: {detected_lang}")
                    except Exception as e:
                        print(f"[WS] ✗ Language detection error: {e}")
                        detected_lang = "hi"

                    print(f"[WS] → Calling agent.get_response() with waiter_speech='{waiter_speech}'...")
                    print(f"[WS] ⏱️  Starting timer...")
                    import time
                    start_time = time.time()
                    # Use detected language for this provider turn so agent replies in provider language
                    lang_to_use = detected_lang if detected_lang else lang
                    # Persist waiter language immediately
                    try:
                        _session_store[session_id]["waiter_lang"] = lang_to_use
                    except Exception:
                        pass
                    bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
                        user_input="",
                        detected_intent="voice_chat",
                        detected_details={},
                        lang=lang_to_use,
                        session_id=session_id,
                        waiter_speech=waiter_speech,
                    )
                    elapsed = time.time() - start_time
                    print(f"[WS] ✓ Agent returned in {elapsed:.2f}s")
                    print(f"[WS] Response details:")
                    print(f"  - bot_response: {bot_response[:150]}...")
                    print(f"  - signal: {signal}")
                    print(f"  - food_options: {food_options}")
                    print(f"  - waiter_lang: {waiter_lang}")
                    print(f"  - status: {status}")

                else:
                    print("[WS] Warning: No valid input received")
                    continue

            except asyncio.TimeoutError as timeout_err:
                print(f"[WS] ✗✗✗ TIMEOUT ✗✗✗")
                import traceback
                traceback.print_exc()
                # Use fallback response
                bot_response = f"PROVIDER_REPLY: ठीक है।\nUSER_SUMMARY: Provider said: {waiter_speech if waiter_speech else 'something'}"
                status = "pending"
                signal = "NONE"
                waiter_lang = "hi"
            except Exception as agent_err:
                print(f"[WS] ✗✗✗ AGENT ERROR ✗✗✗")
                print(f"[WS] Error type: {type(agent_err).__name__}")
                print(f"[WS] Error message: {agent_err}")
                import traceback
                traceback.print_exc()
                # Use fallback response
                bot_response = f"PROVIDER_REPLY: ठीक है।\nUSER_SUMMARY: Provider said: {waiter_speech if waiter_speech else 'something'}"
                status = "pending"
                signal = "NONE"
                waiter_lang = "hi"

            print(f"\n[WS] → Building response payload...")
            response_payload = _build_response(bot_response, status, food_options, waiter_lang, signal)
            response_payload["session_id"] = session_id
            print(f"[WS] ✓ Payload built")

            print(f"\n[WS] 📤 FINAL PAYLOAD TO SEND:")
            print(f"  - bot_response (user sees): {response_payload.get('bot_response', '')[:80]}")
            print(f"  - bot_response_to_provider: {response_payload.get('bot_response_to_provider', '')[:80]}")
            print(f"  - signal: {response_payload.get('signal')}")
            print(f"  - voice_audio: {'YES ({} chars)'.format(len(response_payload.get('voice_audio', ''))) if response_payload.get('voice_audio') else 'NO'}")
            print(f"  - waiter_lang: {response_payload.get('waiter_lang')}")
            print(f"  - status: {response_payload.get('status')}")
            print(f"[WS] → Sending to WebSocket...")
            await websocket.send_json(response_payload)
            print(f"[WS] ✓✓✓ Successfully sent message #{message_count} to frontend ✓✓✓")
            print(f"{'='*100}\n")

        except WebSocketDisconnect as disc:
            print(f"\n[WS] ❌❌❌ CLIENT DISCONNECTED ❌❌❌")
            print(f"[WS] Session: {session_id}")
            print(f"[WS] Disconnect code: {disc.code if hasattr(disc, 'code') else 'N/A'}")
            print(f"[WS] Messages processed: {message_count}")
            break  # Exit loop cleanly — connection is gone
        except Exception as e:
            print(f"\n[WS] ✗✗✗ OUTER ERROR (Message #{message_count}) ✗✗✗")
            print(f"[WS] Error type: {type(e).__name__}")
            print(f"[WS] Error message: {e}")
            import traceback
            print(f"[WS] Full traceback:")
            traceback.print_exc()
            # Send error back but KEEP the connection alive
            try:
                print(f"[WS] → Attempting to send error response...")
                await websocket.send_json({
                    "bot_response": "Something went wrong. Please try again.",
                    "user_summary": "Something went wrong. Please try again.",
                    "signal": "NONE",
                    "status": "pending",
                    "waiter_lang": "hi",
                })
                print("[WS] ✓ Sent error response, continuing...")
            except Exception as send_error:
                print(f"[WS] ✗ Failed to send error response: {send_error}")
                print("[WS] ❌ Closing connection due to send failure")
                break  # WebSocket itself is broken — give up


# ---------------------------------------------------------------------------
# Gemini Live API WebSocket Endpoint (NEW - Bidirectional Voice)
# ---------------------------------------------------------------------------

@app.websocket("/ws/gemini-live/{session_id}")
async def gemini_live_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket proxy for Gemini Multimodal Live API
    Handles bidirectional audio streaming with function calling
    """
    await websocket.accept()
    print(f"[GEMINI_LIVE_WS] Client connected: {session_id}")
    
    # Check for API key
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        await websocket.send_json({"error": "GOOGLE_API_KEY not configured"})
        await websocket.close()
        return
    
    # Create Gemini Live client
    gemini_client = GeminiLiveClient(api_key=api_key)
    
    # Session state
    provider_language = "hi"  # Default Hindi, will auto-detect
    food_items_cache = []
    user_selected_item = None
    
    try:
        # Connect to Gemini Live API
        await gemini_client.connect()
        
        # Setup session with system prompt and tools
        system_prompt = create_system_prompt()
        tools = create_tools_declaration()
        await gemini_client.setup_session(system_prompt, tools)
        
        # Audio/text callbacks
        async def on_audio_received(audio_bytes: bytes):
            """Forward Gemini audio to frontend (24kHz PCM)"""
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
            await websocket.send_json({
                "type": "audio",
                "data": audio_b64,
                "sampleRate": 24000
            })
            
        async def on_text_received(text: str):
            """Forward Gemini text to frontend"""
            print(f"[GEMINI_LIVE_WS] Gemini text: {text}")
            await websocket.send_json({
                "type": "text",
                "data": text
            })
            
        async def on_function_call(func_call: dict):
            """Handle function calls from Gemini"""
            func_name = func_call.get("name")
            func_args = func_call.get("args", {})
            func_id = func_call.get("id", "")
            
            print(f"[GEMINI_LIVE_WS] Function call: {func_name}({func_args})")
            
            # Handle different functions
            if func_name == "show_food_images":
                nonlocal food_items_cache
                food_items_cache = func_args.get("food_items", [])
                user_summary = func_args.get("user_summary", "")
                
                # Send to frontend
                await websocket.send_json({
                    "type": "function_call",
                    "function": "show_food_images",
                    "food_items": food_items_cache,
                    "user_summary": user_summary
                })
                
                # Send success response to Gemini
                await gemini_client.send_function_response(func_id, {
                    "success": True,
                    "message": f"Showed {len(food_items_cache)} food images to user"
                })
                
            elif func_name == "user_selected_item":
                nonlocal user_selected_item, provider_language
                user_selected_item = func_args.get("selected_item", "")
                provider_language = func_args.get("provider_language", "hi")
                
                print(f"[GEMINI_LIVE_WS] User selected: {user_selected_item}, provider lang: {provider_language}")
                
                # Send response to Gemini
                await gemini_client.send_function_response(func_id, {
                    "success": True,
                    "selected_item": user_selected_item
                })
                
            elif func_name == "order_confirmed":
                final_summary = func_args.get("final_summary", "Order confirmed!")
                
                # Send to frontend (triggers .glb animation)
                await websocket.send_json({
                    "type": "function_call",
                    "function": "order_confirmed",
                    "user_summary": final_summary,
                    "signal": "ORDER_DONE"
                })
                
                # Send response to Gemini
                await gemini_client.send_function_response(func_id, {
                    "success": True,
                    "message": "Order confirmed, animation triggered"
                })
                
        # Start Gemini receive loop in background
        receive_task = asyncio.create_task(
            gemini_client.receive_loop(on_audio_received, on_text_received, on_function_call)
        )
        
        # Main loop: receive from frontend and forward to Gemini
        while True:
            try:
                message = await websocket.receive_json()
                msg_type = message.get("type")
                
                if msg_type == "audio":
                    # Frontend sends 16kHz PCM audio (base64)
                    audio_b64 = message.get("data", "")
                    audio_bytes = base64.b64decode(audio_b64)
                    await gemini_client.send_audio(audio_bytes)
                    
                elif msg_type == "text":
                    # Frontend sends text (e.g., ISL interpretation: "hungry")
                    text = message.get("data", "")
                    await gemini_client.send_text(text)
                    print(f"[GEMINI_LIVE_WS] Sent text to Gemini: {text}")
                    
                elif msg_type == "user_selection":
                    # User clicked on a food item
                    selected_item = message.get("item", "")
                    # Send to Gemini as text trigger
                    await gemini_client.send_text(f"User selected: {selected_item}")
                    
                elif msg_type == "user_confirmation":
                    # User confirmed order
                    await gemini_client.send_text("User confirms the order")
                    
                elif msg_type == "ping":
                    # Heartbeat
                    await websocket.send_json({"type": "pong"})
                    
            except WebSocketDisconnect:
                print(f"[GEMINI_LIVE_WS] Client disconnected: {session_id}")
                break
            except Exception as e:
                print(f"[GEMINI_LIVE_WS] Error: {e}")
                import traceback
                traceback.print_exc()
                break
                
    finally:
        # Cleanup
        if gemini_client:
            await gemini_client.disconnect()
        receive_task.cancel()
        print(f"[GEMINI_LIVE_WS] Session ended: {session_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
