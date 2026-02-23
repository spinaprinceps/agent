import os
import io
import json
import base64
from langdetect import detect, DetectorFactory

# Force consistent detection
DetectorFactory.seed = 0
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, Form
from fastapi.middleware.cors import CORSMiddleware
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from agents.service_agent import get_or_create_agent, GraphAgent
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
    location="us-central1"  # Gemini 2.0 Flash is most reliable in us-central1
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
        "en": {"language_code": "en-IN", "name": "en-IN-Wavenet-A"},   # female
        "kn": {"language_code": "kn-IN", "name": "kn-IN-Wavenet-A"},   # female
        "ta": {"language_code": "ta-IN", "name": "ta-IN-Wavenet-A"},   # female
    }
    return voice_map.get(lang, voice_map["hi"])


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

    # Mission 5.0 (FIX): Extract provider reply and user summary
    provider_reply = ""
    deaf_summary = ""
    if "DEAF_SUMMARY:" in clean_text:
        parts = clean_text.split("DEAF_SUMMARY:")
        provider_reply = parts[0].replace("PROVIDER_REPLY:", "").strip()
        deaf_summary = parts[1].strip()
    else:
        # Fallback for simple turns or if formatting fails
        deaf_summary = clean_text
        provider_reply = clean_text

    # Mission 4.0/5.0: Extract menu items if present in the DEAF_SUMMARY tag
    # User requested SHOW_PLACEHOLDER_IMAGES signal
    items = _extract_food_tags(provider_reply)
    
    # Strip any signal tags from display text
    user_display = deaf_summary.split("[[")[0].strip()
    
    payload: dict = {
        "bot_response": user_display,
        "bot_response_to_provider": provider_reply,
        "user_summary": user_display,
        "status": status,
        "waiter_lang": waiter_lang,
    }

    if items and not agent_signal:
        payload["signal"] = "SHOW_PLACEHOLDER_IMAGES"
        payload["items"] = items

    if food_options:
        # Compatibility with existing FoodSelection
        payload["food_options"] = food_options
        if not payload.get("signal"):
             payload["signal"] = "SHOW_FOODS"

    if agent_signal:
        payload["signal"] = agent_signal

    if "WORK_DONE" in bot_response or status == "done":
        payload["signal"] = "WORK_DONE"
        payload["order_success"] = True 
        payload["signal_alt"] = "ORDER_SUCCESS"

    # Generate TTS audio for the "waiter/provider" side in THEIR language
    voice_audio = generate_tts(provider_reply, waiter_lang)
    if voice_audio:
        payload["voice_audio"] = voice_audio

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
        "Analyze this video of Indian Sign Language carefully. "
        "Transcribe the sign to English text and detect the intent (food_order, book_transport, book_appointment). "
        "Extract details (e.g., what food, where to go). "
        "Return ONLY a JSON object: {\"text\": \"string\", \"intent\": \"string\", \"details\": {}}"
    )

    video_part = Part.from_data(data=video_bytes, mime_type="video/webm")

    try:
        response = gemini_model.generate_content(
            [prompt, video_part],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.95,
            )
        )

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
    print(f"[WS] Connected: {session_id}")
    
    agent = get_or_create_agent(session_id, lang="hi")
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            print(f"[DEBUG] [WS] Received: {raw_data}")
            payload = json.loads(raw_data)

            input_text = payload.get("text") or payload.get("waiter_speech", "")
            action = payload.get("action")
            lang = payload.get("lang", "hi")
            item = payload.get("item")

            # Single task: Detect language of every message
            detected_lang = waiter_lang # fallback
            if input_text and not action:
                 try:
                     detected_lang = detect(input_text)
                     print(f"[DEBUG] [LANG] Single-task detect: {detected_lang}")
                 except:
                     detected_lang = "en"

            # Mission 4.0/5.0 (FIX): Handle selection actions
            if (action == "select_item" or action == "user_selection") and item:
                input_text = f"User selected: {item}"

            # Execute the agent turn
            bot_response, status, food_options, waiter_lang, signal = await agent.get_response(
                user_input=input_text,
                detected_intent="voice_chat",
                detected_details={},
                lang=lang,
                session_id=session_id,
                action=action,
                waiter_lang=detected_lang # Pass detected lang
            )
            
            print(f"[DEBUG] [AGENT] Response: {bot_response}, Signal: {signal}")

            # Build and send response
            response_payload = _build_response(bot_response, status, food_options, waiter_lang or detected_lang, signal)
            response_payload["session_id"] = session_id
            
            # Mission 3.0: Explicit success signal for terminal confirmation
            if input_text and ("order confirmed" in input_text.lower() or "payment done" in input_text.lower() or "ready" in input_text.lower()):
                response_payload["signal"] = "ORDER_SUCCESS"
            
            await websocket.send_json(response_payload)
            print(f"[DEBUG] [WS] Sent to client: {bot_response[:100]}...")

    except WebSocketDisconnect:
        print(f"[WS] Disconnected: {session_id}")
    except Exception as e:
        print(f"[WS] Error: {e}")
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
