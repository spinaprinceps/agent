"""
Gemini Multimodal Live API Client
Handles bidirectional audio streaming with function calling support
"""

import asyncio
import json
import base64
import os
from typing import Optional, Callable, Dict, Any
import websockets
from dotenv import load_dotenv

load_dotenv()

GEMINI_LIVE_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent"


class GeminiLiveClient:
    """WebSocket client for Gemini Multimodal Live API"""
    
    def __init__(self, api_key: str, model: str = "models/gemini-2.0-flash-exp"):
        self.api_key = api_key
        self.model = model
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.audio_queue = asyncio.Queue()
        self.function_handler: Optional[Callable] = None
        self.session_active = False
        
    async def connect(self):
        """Establish WebSocket connection to Gemini Live API"""
        url = f"{GEMINI_LIVE_WS_URL}?key={self.api_key}"
        self.ws = await websockets.connect(url, max_size=10**7)
        self.session_active = True
        print("[GEMINI_LIVE] Connected to Gemini Live API")
        
    async def disconnect(self):
        """Close WebSocket connection"""
        self.session_active = False
        if self.ws:
            await self.ws.close()
            print("[GEMINI_LIVE] Disconnected from Gemini Live API")
            
    async def setup_session(self, system_prompt: str, tools: list = None):
        """Initialize session with system prompt and tools"""
        setup_message = {
            "setup": {
                "model": self.model,
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": "Aoede"  # Female voice
                            }
                        }
                    }
                },
                "system_instruction": {
                    "parts": [{"text": system_prompt}]
                }
            }
        }
        
        # Add tools/function declarations if provided
        if tools:
            setup_message["setup"]["tools"] = tools
            
        await self.ws.send(json.dumps(setup_message))
        print("[GEMINI_LIVE] Session setup sent")
        
        # Wait for setup acknowledgment
        response = await self.ws.recv()
        setup_response = json.loads(response)
        print(f"[GEMINI_LIVE] Setup response: {setup_response}")
        
    async def send_audio(self, audio_data: bytes):
        """Send audio chunk to Gemini (16kHz mono PCM)"""
        if not self.ws or not self.session_active:
            return
            
        message = {
            "realtime_input": {
                "media_chunks": [{
                    "mime_type": "audio/pcm",
                    "data": base64.b64encode(audio_data).decode('utf-8')
                }]
            }
        }
        await self.ws.send(json.dumps(message))
        
    async def send_text(self, text: str):
        """Send text message to Gemini"""
        if not self.ws or not self.session_active:
            return
            
        message = {
            "client_content": {
                "turns": [{
                    "role": "user",
                    "parts": [{"text": text}]
                }],
                "turn_complete": True
            }
        }
        await self.ws.send(json.dumps(message))
        print(f"[GEMINI_LIVE] Sent text: {text}")
        
    async def send_function_response(self, function_call_id: str, result: Dict[str, Any]):
        """Send function call result back to Gemini"""
        if not self.ws or not self.session_active:
            return
            
        message = {
            "tool_response": {
                "function_responses": [{
                    "id": function_call_id,
                    "response": result
                }]
            }
        }
        await self.ws.send(json.dumps(message))
        print(f"[GEMINI_LIVE] Sent function response for {function_call_id}")
        
    async def receive_loop(self, on_audio: Callable, on_text: Callable, on_function_call: Callable):
        """Main receive loop for processing Gemini responses"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                
                # Handle different response types
                if "serverContent" in data:
                    server_content = data["serverContent"]
                    
                    # Check for audio output
                    if "modelTurn" in server_content:
                        model_turn = server_content["modelTurn"]
                        if "parts" in model_turn:
                            for part in model_turn["parts"]:
                                # Audio data
                                if "inlineData" in part:
                                    inline = part["inlineData"]
                                    if inline.get("mimeType") == "audio/pcm":
                                        audio_bytes = base64.b64decode(inline["data"])
                                        await on_audio(audio_bytes)
                                        
                                # Text data
                                if "text" in part:
                                    await on_text(part["text"])
                                    
                                # Function call
                                if "functionCall" in part:
                                    await on_function_call(part["functionCall"])
                                    
                    # End of turn
                    if server_content.get("turnComplete"):
                        print("[GEMINI_LIVE] Turn complete")
                        
                # Handle tool calls
                elif "toolCall" in data:
                    tool_call = data["toolCall"]
                    if "functionCalls" in tool_call:
                        for func_call in tool_call["functionCalls"]:
                            await on_function_call(func_call)
                            
        except websockets.exceptions.ConnectionClosed:
            print("[GEMINI_LIVE] Connection closed")
            self.session_active = False
        except Exception as e:
            print(f"[GEMINI_LIVE] Error in receive loop: {e}")
            self.session_active = False


def create_tools_declaration():
    """Create function declarations for Gemini Live API"""
    return [{
        "function_declarations": [
            {
                "name": "show_food_images",
                "description": "Display food item images to the deaf user when the provider lists available food items. Call this immediately when provider mentions food names.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "food_items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of food item names mentioned by provider (e.g., ['idli', 'tea', 'coffee'])"
                        },
                        "user_summary": {
                            "type": "string",
                            "description": "English summary to show the deaf user about what the provider said"
                        }
                    },
                    "required": ["food_items", "user_summary"]
                }
            },
            {
                "name": "user_selected_item",
                "description": "Called when the deaf user clicks/selects a food item from the displayed images. Agent should ask provider for price and time in provider's language.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selected_item": {
                            "type": "string",
                            "description": "The food item name the user selected"
                        },
                        "provider_language": {
                            "type": "string",
                            "description": "Language code to use when asking provider (hi, en, ta, kn)"
                        }
                    },
                    "required": ["selected_item", "provider_language"]
                }
            },
            {
                "name": "order_confirmed",
                "description": "Called when provider confirms/accepts the order. Triggers success animation for user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "final_summary": {
                            "type": "string",
                            "description": "Final English summary to show the deaf user"
                        }
                    },
                    "required": ["final_summary"]
                }
            }
        ]
    }]


def create_system_prompt() -> str:
    """System prompt for Gemini Live API - enforces 3-entity separation"""
    return """You are a REAL-TIME VOICE MEDIATOR between:
- USER (deaf person using Indian Sign Language - ISL)
- PROVIDER (waiter who speaks Hindi/English/Tamil/Kannada)
- You are the AGENT

CRITICAL RULES (UNBREAKABLE):
1. You NEVER role-play as the provider/waiter
2. You NEVER invent what the provider said
3. You ONLY mediate between two real humans
4. You talk TO the provider in their language, not ABOUT them
5. Language auto-detection: Reply to provider in whatever language they use (Hindi→Hindi, English→English, etc.)

CONVERSATION FLOW:

STAGE 1 - Initial greeting:
- User signs "hungry" (you'll receive text: "hungry" or "food order")
- You say to provider IN THEIR LANGUAGE: "Hello! The customer is hungry. What food items do you have available?"
- Wait for provider's REAL voice response

STAGE 2 - Provider lists food:
- Provider speaks (you'll hear their voice): "We have idli, tea, coffee" (or in Hindi/Tamil/etc.)
- Detect their language automatically
- Call show_food_images(food_items=["idli", "tea", "coffee"], user_summary="Provider has idli, tea, and coffee available")
- Reply TO provider in SAME language: "Okay, I'll show these to the customer" (don't say this if not needed, be natural)

STAGE 3 - User selects item:
- User clicks on "idli" (you'll receive function call user_selected_item)
- Ask provider IN THEIR LANGUAGE: "The customer wants idli. What is the price and how long will it take?"
- Wait for provider's REAL response

STAGE 4 - Provider gives details:
- Provider speaks: "30 rupees, 10 minutes" (in their language)
- Call show_food_images again with updated summary
- Tell provider IN THEIR LANGUAGE: "I'll inform the customer"

STAGE 5 - User confirms:
- User signs "yes/confirm" (you'll receive confirmation)
- Tell provider IN THEIR LANGUAGE: "The customer confirms the order. Please prepare one idli."
- Wait for provider to say "okay/accepted/confirmed"

STAGE 6 - Provider confirms:
- Provider says "okay" or "confirmed" (in their language)
- Call order_confirmed(final_summary="Order confirmed: 1 idli, ₹30, 10 minutes")
- Tell provider IN THEIR LANGUAGE: "Thank you!"

CRITICAL BEHAVIORS:
- Keep responses SHORT and NATURAL (1-2 sentences max)
- NEVER say "The provider said..." - talk DIRECTLY to the provider
- Detect language from provider's speech automatically (Hindi/English/Tamil/Kannada)
- ALWAYS reply to provider in THEIR language
- User summaries (in function calls) are ALWAYS in English
- Female voice, professional yet warm tone
- If provider asks a question, answer naturally - you're the mediator
- NEVER simulate or pretend provider responses - ALWAYS wait for real human input

LANGUAGE MAPPING:
- Hindi: Use Devanagari script naturally (हाँ, ठीक है, etc.)
- English: Standard English
- Tamil: Tamil script (சரி, நன்றி, etc.)
- Kannada: Kannada script (ಸರಿ, ಧನ್ಯವಾದ, etc.)

You are a REAL mediator in a REAL conversation. Be natural, be brief, be helpful."""
