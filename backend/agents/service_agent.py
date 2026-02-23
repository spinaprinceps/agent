"""
CLEAN 3-ENTITY AGENTIC ORCHESTRATION SERVICE AGENT
Strict mediator between USER (deaf person) and PROVIDER (waiter).
NEVER role-plays. NEVER invents content. Temperature = 0.95 ALWAYS.
"""

import os
import json
import re
import asyncio
from typing import Annotated, Any, Dict, List, Optional, Tuple
from langdetect import detect, DetectorFactory
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv

load_dotenv()

# Force consistent language detection
DetectorFactory.seed = 0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

from typing import TypedDict

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    order_details: Dict[str, Any]
    current_service: str
    lang: str
    is_done: bool
    food_options: List[str]
    waiter_lang: str
    waiter_mode_active: bool
    last_provider_message: str
    selected_item: str
    # Parsed output fields (extracted by process_response node)
    provider_reply: str
    user_summary: str
    signal: str


# ---------------------------------------------------------------------------
# LLM Configuration
# ---------------------------------------------------------------------------

llm = ChatVertexAI(
    model_name="gemini-2.0-flash-001",
    project=os.getenv("GOOGLE_PROJECT_ID"),
    location="us-central1",
    temperature=0.95,  # UNBREAKABLE: Always 0.95
    top_p=0.95,
    timeout=20,  # 20 second timeout for LLM calls
)

food_parser_llm = ChatVertexAI(
    model_name="gemini-2.0-flash-001",
    project=os.getenv("GOOGLE_PROJECT_ID"),
    location="us-central1",
    temperature=0.95,  # UNBREAKABLE: Always 0.95
    top_p=0.95,
    timeout=15,  # 15 second timeout for food parsing
)


# ---------------------------------------------------------------------------
# Language Detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Detect provider language using langdetect.
    Returns: 'hi', 'en', 'ta', 'kn', or defaults to 'en'
    """
    if not text or len(text.strip()) < 3:
        return "en"
    
    try:
        detected = detect(text)
        # Map to supported languages
        lang_map = {
            "hi": "hi",  # Hindi
            "en": "en",  # English
            "ta": "ta",  # Tamil
            "kn": "kn",  # Kannada
            "te": "hi",  # Telugu -> fallback to Hindi (similar script)
            "mr": "hi",  # Marathi -> fallback to Hindi (similar script)
        }
        return lang_map.get(detected, "en")
    except Exception as e:
        print(f"[LANG_DETECT] Error: {e}, defaulting to 'en'")
        return "en"


# ---------------------------------------------------------------------------
# Food Item Parser
# ---------------------------------------------------------------------------

async def parse_food_items(text: str, detected_lang: str) -> List[str]:
    """
    Extract ONLY the food item names mentioned in the provider's message.
    Uses keyword matching first (fast), then Gemini as fallback.
    """
    if not text:
        return []

    # Fast keyword match (handles transliterated / common foods)
    # Keys are search terms, values are canonical names
    FOOD_KEYWORDS = {
        "idli": "idli", "इडली": "idli",
        "dosa": "dosa", "डोसा": "dosa",
        "vada": "vada", "वड़ा": "vada", "wada": "vada",
        "samosa": "samosa", "समोसा": "samosa",
        "biryani": "biryani", "बिरयानी": "biryani",
        "rice": "rice", "चावल": "rice",
        "roti": "roti", "रोटी": "roti", "chapati": "roti",
        "dal": "dal", "दाल": "dal",
        "coffee": "coffee", "कॉफी": "coffee",
        "tea": "tea", "टी": "tea", "chai": "chai", "चाय": "chai",
        "juice": "juice", "जूस": "juice",
        "pizza": "pizza", "burger": "burger", "sandwich": "sandwich",
        "poha": "poha", "पोहा": "poha",
        "upma": "upma", "उपमा": "upma",
        "puri": "puri", "पूरी": "puri",
    }

    lower = text.lower()
    found = []
    for kw, canonical in FOOD_KEYWORDS.items():
        if kw.lower() in lower and canonical not in found:
            found.append(canonical)

    if found:
        print(f"[FOOD_PARSE] Keyword match found: {found}")
        return found[:6]

    # Fallback: LLM extraction (run in thread pool to avoid blocking)
    prompt = f"""Extract ONLY the food/drink item names from this text.
Return as a JSON list of strings. No explanations, just the item names.
If no items found, return empty list [].

Text: {text}

Example output: ["idli", "tea", "coffee"]
"""
    try:
        response = await asyncio.to_thread(
            food_parser_llm.invoke,
            [HumanMessage(content=prompt)]
        )
        content = response.content.strip()
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        if match:
            items = json.loads(match.group(0))
            normalized = []
            for item in items:
                if isinstance(item, str) and item.strip():
                    normalized.append(item.strip().lower())
            print(f"[FOOD_PARSE] LLM found: {normalized}")
            return list(dict.fromkeys(normalized))[:6]
        return []
    except Exception as e:
        print(f"[FOOD_PARSE] Error: {e}")
        return []


# ---------------------------------------------------------------------------
# Translation Helper
# ---------------------------------------------------------------------------

def translate_text(text: str, target_lang: str) -> str:
    """
    Translate text to target language using Gemini.
    Temperature = 0.95 (strict).
    """
    if target_lang == "en":
        return text
    
    lang_names = {
        "hi": "Hindi",
        "ta": "Tamil",
        "kn": "Kannada",
        "en": "English"
    }
    
    target_name = lang_names.get(target_lang, "Hindi")
    
    prompt = f"""Translate the following text to {target_name}.
Return ONLY the translation, no explanations.

Text: {text}

Translation:"""
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()
    except Exception as e:
        print(f"[TRANSLATION] Error: {e}")
        return text


# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------

def build_system_prompt(state: AgentState) -> str:
    """
    Build the UNBREAKABLE system prompt for the mediator agent.
    """
    waiter_lang = state.get("waiter_lang", "en")
    food_options = state.get("food_options", [])
    selected_item = state.get("selected_item", "")
    last_provider_msg = state.get("last_provider_message", "")
    
    lang_names = {
        "hi": "Hindi",
        "en": "English",
        "ta": "Tamil",
        "kn": "Kannada"
    }
    
    provider_lang_name = lang_names.get(waiter_lang, "English")
    
    return f"""YOU ARE THE AGENT (MEDIATOR AI) - UNBREAKABLE RULES

=== 3-ENTITY ARCHITECTURE (STRICT) ===
1. USER (deaf person): Communicates via ISL video/signs → receives English summaries
2. PROVIDER (waiter): Speaks in ANY language → you detect and adapt every turn
3. AGENT (you): NEVER role-play as provider. ONLY mediate between user and provider.

=== YOUR RESPONSIBILITIES ===
- Relay provider's words to user in simple English
- Ask provider questions in provider's current language ({provider_lang_name})
- Detect provider language EVERY message and adapt instantly
- Extract food items when provider lists them
- Handle user selections and ask provider for details

=== CURRENT CONTEXT ===
Provider Language: {waiter_lang} ({provider_lang_name})
Food Options: {json.dumps(food_options)}
Selected Item: {selected_item or "None"}
Last Provider Message: {last_provider_msg}

=== OUTPUT FORMAT (MANDATORY) ===
Every response MUST follow this exact structure:

PROVIDER_REPLY: [Your question/response to provider in {provider_lang_name}]
USER_SUMMARY: [Simple English summary for deaf user]
SIGNAL: [One of: NONE, SHOW_PLACEHOLDER_IMAGES, ORDER_DONE]

=== FLOW RULES ===

FIRST TURN (user signs hungry/eat, no provider conversation started yet):
PROVIDER_REPLY: [NONE]
USER_SUMMARY: I understand you're hungry. Let me check with the Provider what is available.
SIGNAL: SHOW_PROVIDER_BUTTON

WHEN USER CLICKS "SPEAK TO PROVIDER" BUTTON:
PROVIDER_REPLY: Hello Provider, what food items do you have available today?
USER_SUMMARY: Checking with the Provider...
SIGNAL: WAITER_ACTIVE

PROVIDER LISTS ITEMS (e.g., "हमारे पास इडली और चाय है"):
PROVIDER_REPLY: [Acknowledgment in {provider_lang_name}]
USER_SUMMARY: Provider says [items] are available. Please select one.
SIGNAL: SHOW_PLACEHOLDER_IMAGES

USER SELECTS ITEM (e.g., "idli"):
PROVIDER_REPLY: ग्राहक [item] ऑर्डर करना चाहते हैं। कीमत क्या है? कितना समय लगेगा?
USER_SUMMARY: I've asked the waiter about the price and preparation time for [item].
SIGNAL: NONE

PROVIDER GIVES DETAILS (e.g., "₹50, 10 मिनट"):
PROVIDER_REPLY: [Confirmation in {provider_lang_name}]
USER_SUMMARY: Provider says ₹[price], ready in [time] minutes. Shall I confirm your order?
SIGNAL: NONE

PROVIDER CONFIRMS (mentions "confirmed", "order accepted", "payment received"):
PROVIDER_REPLY: धन्यवाद
USER_SUMMARY: Your order is confirmed! The food will arrive soon.
SIGNAL: ORDER_DONE

=== ABSOLUTE PROHIBITIONS ===
❌ NEVER role-play as the provider/waiter
❌ NEVER invent food items, prices, or times
❌ NEVER use information from your training data
❌ ONLY use what the provider said in the CURRENT message
❌ NEVER list foods from memory

=== DETECTION & ADAPTATION ===
- Language is detected per provider message and stored
- You MUST respond to provider in THEIR detected language
- User summaries ALWAYS in English
- Update response language if provider switches languages mid-conversation
"""


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------

def call_model(state: AgentState) -> dict:
    """
    Main agent node: processes input and generates structured response.
    """
    messages = state["messages"]
    system_prompt = build_system_prompt(state)
    
    full_messages = [SystemMessage(content=system_prompt)] + list(messages)
    
    print(f"[AGENT] Invoking LLM with {len(messages)} messages")
    response = llm.invoke(full_messages)
    
    return {"messages": [response]}


def process_response(state: AgentState) -> dict:
    """
    Post-process the agent's response to extract structured outputs.
    """
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    
    if not isinstance(last_msg, AIMessage):
        return {}
    
    content = last_msg.content or ""
    
    # Parse structured response
    provider_reply = ""
    user_summary = ""
    signal = "NONE"
    
    # Extract PROVIDER_REPLY
    provider_match = re.search(r'PROVIDER_REPLY:\s*(.+?)(?=USER_SUMMARY:|SIGNAL:|$)', content, re.DOTALL | re.IGNORECASE)
    if provider_match:
        provider_reply = provider_match.group(1).strip()
    
    # Extract USER_SUMMARY
    summary_match = re.search(r'USER_SUMMARY:\s*(.+?)(?=SIGNAL:|$)', content, re.DOTALL | re.IGNORECASE)
    if summary_match:
        user_summary = summary_match.group(1).strip()
    
    # Extract SIGNAL
    signal_match = re.search(r'SIGNAL:\s*([\w_]+)', content, re.IGNORECASE)
    if signal_match:
        signal = signal_match.group(1).strip().upper()
    
    # Detect completion signals in provider reply
    completion_keywords = ["order accepted", "confirmed", "payment received", "order confirmed"]
    last_provider = state.get("last_provider_message", "").lower()
    if any(kw in last_provider for kw in completion_keywords):
        signal = "ORDER_DONE"

    # HARD OVERRIDE: first turn must ALWAYS show the provider button, never talk to provider
    if not state.get("waiter_mode_active") and not state.get("last_provider_message"):
        signal = "SHOW_PROVIDER_BUTTON"
        provider_reply = "[NONE]"
        if not user_summary or len(user_summary) < 5:
            user_summary = "I understand you. Let me check with the Provider what is available."
        print(f"[PROCESS_RESPONSE] First-turn override → SHOW_PROVIDER_BUTTON, provider_reply cleared")
    
    updates = {
        "provider_reply": provider_reply,
        "user_summary": user_summary,
        "signal": signal,
    }
    
    print(f"[PROCESS_RESPONSE] Signal: {signal}, Provider Reply: {provider_reply[:50]}..., User Summary: {user_summary[:50]}...")
    
    return updates


# ---------------------------------------------------------------------------
# Build Graph
# ---------------------------------------------------------------------------

workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("process", process_response)

workflow.set_entry_point("agent")
workflow.add_edge("agent", "process")
workflow.add_edge("process", END)

memory = MemorySaver()
compiled_graph = workflow.compile(checkpointer=memory)


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

_session_store: Dict[str, dict] = {}


def get_or_create_agent(session_id: str, lang: str = "hi") -> "GraphAgent":
    """Get or create a session agent."""
    if session_id not in _session_store:
        _session_store[session_id] = {
            "messages": [],
            "order_details": {},
            "current_service": "food_order",
            "lang": lang,
            "is_done": False,
            "food_options": [],
            "waiter_lang": "en",
            "waiter_mode_active": False,
            "last_provider_message": "",
            "selected_item": "",
            "provider_reply": "",
            "user_summary": "",
            "signal": "NONE",
        }
    return GraphAgent(session_id, lang)


class GraphAgent:
    """Agent wrapper for session-based interactions."""
    
    def __init__(self, session_id: str, lang: str = "hi"):
        self.session_id = session_id
        self.lang = lang
        self.config = {"configurable": {"thread_id": session_id}}
    
    async def get_response(
        self,
        user_input: str = "",
        detected_intent: str = "",
        detected_details: Dict[str, Any] = None,
        lang: str = "hi",
        session_id: str = "",
        action: str = None,
        waiter_speech: str = "",
        selected_item: str = "",
    ) -> Tuple[str, str, List[str], str, str]:
        """
        Process input and return (bot_response, status, food_options, waiter_lang, signal).

        DETERMINISTIC paths (no LLM) for reliability:
          • user signs (first turn)         → SHOW_PROVIDER_BUTTON
          • speak_to_waiter                 → WAITER_ACTIVE + greeting TTS
          • user selects food item          → ask provider for price/time (LLM)
          • provider speaks (waiter_speech) → full LLM mediation
        """
        session_state = _session_store.get(self.session_id, {})
        waiter_lang = session_state.get("waiter_lang", "en")
        food_options = session_state.get("food_options", [])

        # ── CASE 1: User just signed (first turn) ────────────────────────────
        if user_input and not session_state.get("waiter_mode_active"):
            print(f"[AGENT] DETERMINISTIC first turn for sign: {user_input}")
            user_summary  = "I understand you. Let me check with the Provider what is available."
            provider_reply = "[NONE]"
            signal         = "SHOW_PROVIDER_BUTTON"
            bot_response   = f"PROVIDER_REPLY: {provider_reply}\nUSER_SUMMARY: {user_summary}"
            return bot_response, "pending", food_options, waiter_lang, signal

        # ── CASE 2: User clicked "Speak to Provider" ─────────────────────────
        if action == "speak_to_waiter":
            print("[AGENT] DETERMINISTIC speak_to_waiter")
            # Decide greeting language based on detected waiter_lang
            lang_greetings = {
                "hi": "नमस्ते! आज आपके पास कौन से खाने के आइटम उपलब्ध हैं?",
                "en": "Hello! What food items do you have available today?",
                "ta": "வணக்கம்! இன்று என்ன உணவு வகைகள் கிடைக்கின்றன?",
                "kn": "ನಮಸ್ಕಾರ! ಇಂದು ಯಾವ ಆಹಾರ ಪದಾರ್ಥಗಳು ಲಭ್ಯವಿವೆ?",
            }
            provider_reply = lang_greetings.get(waiter_lang, lang_greetings["en"])
            user_summary   = "Checking with the Provider about available food items..."
            signal         = "WAITER_ACTIVE"
            _session_store[self.session_id]["waiter_mode_active"] = True
            bot_response   = f"PROVIDER_REPLY: {provider_reply}\nUSER_SUMMARY: {user_summary}"
            print(f"[AGENT] Greeting provider in '{waiter_lang}': {provider_reply}")
            return bot_response, "pending", food_options, waiter_lang, signal

        # ── CASE 3: Provider spoke — full LLM mediation ──────────────────────
        if waiter_speech:
            print("\n" + "#"*100)
            print(f"[AGENT] 🎯 CASE 3: Provider spoke (waiter_speech={waiter_speech})")
            print(f"#"*100)
            print(f"[AGENT] → Step 1: Detect language")
            detected_lang = detect_language(waiter_speech)
            print(f"[AGENT] ✓ Language detected: {detected_lang}")
            
            print(f"[AGENT] → Step 2: Parse food items")
            food_items = await parse_food_items(waiter_speech, detected_lang)
            print(f"[AGENT] ✓ Food items parsed: {food_items}")

            # Persist detected language + message
            _session_store[self.session_id]["waiter_lang"]           = detected_lang
            _session_store[self.session_id]["last_provider_message"] = waiter_speech
            if food_items:
                _session_store[self.session_id]["food_options"] = food_items
                food_options = food_items
            waiter_lang = detected_lang

            # Build targeted LLM prompt (no format ambiguity)
            lang_names = {"hi": "Hindi", "en": "English", "ta": "Tamil", "kn": "Kannada"}
            lang_name  = lang_names.get(detected_lang, "the detected language")

            selected = session_state.get("selected_item", "")
            context  = f"Selected item: {selected}" if selected else "No item selected yet."

            system = f"""You are an AI mediator between a deaf USER and a PROVIDER (waiter).
The provider just spoke in {lang_name}. Relay the information to the user in simple English
and reply to the provider in {lang_name}.

CONTEXT: {context}
FOOD ITEMS DETECTED: {json.dumps(food_items)}

Reply in EXACTLY this format (no extra text):
PROVIDER_REPLY: <your reply to provider in {lang_name}>
USER_SUMMARY: <simple English summary for the deaf user>
SIGNAL: <one of: NONE, SHOW_PLACEHOLDER_IMAGES, ORDER_DONE>

Rules:
- If provider listed food items, set SIGNAL to SHOW_PLACEHOLDER_IMAGES
- If provider confirmed order/payment, set SIGNAL to ORDER_DONE
- Otherwise SIGNAL is NONE
- NEVER invent info not in the provider's message
"""
            human = f"Provider said: {waiter_speech}"
            print(f"[AGENT] → Step 3: Call LLM (START)")
            print(f"[AGENT] Using asyncio.to_thread to avoid blocking...")
            try:
                import time
                llm_start = time.time()
                # Run synchronous LLM call in thread pool to avoid blocking event loop
                print(f"[AGENT] ⏱️  Invoking LLM...")
                response = await asyncio.to_thread(
                    llm.invoke,
                    [SystemMessage(content=system), HumanMessage(content=human)]
                )
                llm_elapsed = time.time() - llm_start
                content = response.content.strip()
                print(f"[AGENT] ✓✓✓ LLM responded in {llm_elapsed:.2f}s ✓✓✓")
                print(f"[AGENT] LLM raw output ({len(content)} chars):\n{content}\n")

                # Parse structured response
                pr_m = re.search(r'PROVIDER_REPLY:\s*(.+?)(?=USER_SUMMARY:|SIGNAL:|$)', content, re.DOTALL | re.IGNORECASE)
                us_m = re.search(r'USER_SUMMARY:\s*(.+?)(?=SIGNAL:|$)', content, re.DOTALL | re.IGNORECASE)
                sg_m = re.search(r'SIGNAL:\s*(\w+)', content, re.IGNORECASE)

                provider_reply = pr_m.group(1).strip() if pr_m else "ठीक है, धन्यवाद।"
                user_summary   = us_m.group(1).strip() if us_m else "Provider replied."
                signal         = sg_m.group(1).strip().upper() if sg_m else "NONE"
                print(f"[AGENT] ✓ Parsed LLM output:")
                print(f"  - provider_reply: {provider_reply}")
                print(f"  - user_summary: {user_summary}")
                print(f"  - signal: {signal}")
            except Exception as llm_err:
                print(f"[AGENT] ✗✗✗ LLM ERROR ✗✗✗")
                print(f"[AGENT] Error type: {type(llm_err).__name__}")
                print(f"[AGENT] Error message: {llm_err}")
                import traceback
                traceback.print_exc()
                provider_reply = "ठीक है।"
                user_summary   = f"Provider said: {waiter_speech}"
                signal         = "SHOW_PLACEHOLDER_IMAGES" if food_items else "NONE"
                print(f"[AGENT] Using fallback response")

            # Safety: if food found, always show images
            if food_items and signal not in ("SHOW_PLACEHOLDER_IMAGES", "ORDER_DONE"):
                signal = "SHOW_PLACEHOLDER_IMAGES"

            print(f"[AGENT] → Step 4: Update session store")
            _session_store[self.session_id].update({
                "food_options": food_options,
                "waiter_lang":  waiter_lang,
            })
            print(f"[AGENT] ✓ Session updated")
            
            bot_response = f"PROVIDER_REPLY: {provider_reply}\nUSER_SUMMARY: {user_summary}"
            print(f"\n[AGENT] ✓✓✓ CASE 3 COMPLETE - FINAL RESPONSE ✓✓✓")
            print(f"  - provider_reply: {provider_reply}")
            print(f"  - user_summary: {user_summary}")
            print(f"  - signal: {signal}")
            print(f"  - food_options: {food_options}")
            print(f"  - waiter_lang: {waiter_lang}")
            print("#"*80 + "\n")
            return bot_response, "pending", food_options, waiter_lang, signal

        # ── CASE 4: User selected a food item ────────────────────────────────
        if action == "user_selection" and selected_item:
            print(f"[AGENT] DETERMINISTIC user_selection: {selected_item}")
            _session_store[self.session_id]["selected_item"] = selected_item

            lang_names = {"hi": "Hindi", "en": "English", "ta": "Tamil", "kn": "Kannada"}
            lang_name  = lang_names.get(waiter_lang, "the detected language")

            system = f"""You are an AI mediator. The deaf user selected '{selected_item}'.
Ask the provider for price and preparation time in {lang_name}.
Reply in EXACTLY this format:
PROVIDER_REPLY: <ask about price and time in {lang_name}>
USER_SUMMARY: I've asked the provider about {selected_item}. Waiting for details.
SIGNAL: NONE"""

            response     = await asyncio.to_thread(
                llm.invoke,
                [SystemMessage(content=system), HumanMessage(content=f"User selected: {selected_item}")]
            )
            content      = response.content.strip()
            pr_m         = re.search(r'PROVIDER_REPLY:\s*(.+?)(?=USER_SUMMARY:|SIGNAL:|$)', content, re.DOTALL | re.IGNORECASE)
            provider_reply = pr_m.group(1).strip() if pr_m else f"Customer wants {selected_item}. What is the price and preparation time?"
            user_summary   = f"I've asked the provider about {selected_item}. Waiting for details."
            signal         = "NONE"
            bot_response   = f"PROVIDER_REPLY: {provider_reply}\nUSER_SUMMARY: {user_summary}"
            return bot_response, "pending", food_options, waiter_lang, signal

        # ── Fallback ──────────────────────────────────────────────────────────
        print("[AGENT] WARNING: No valid input matched, returning idle response")
        return "PROVIDER_REPLY: [NONE]\nUSER_SUMMARY: Ready.", "pending", food_options, waiter_lang, "NONE"
