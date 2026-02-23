import os
import json
import re
from typing import Annotated, Any, Dict, List, Optional

from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv

load_dotenv()

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


# ---------------------------------------------------------------------------
# Waiter LLM (separate invocation, no tools, waiter persona)
# ---------------------------------------------------------------------------

_waiter_llm = ChatVertexAI(
    model_name="gemini-2.0-flash-001",
    project=os.getenv("GOOGLE_PROJECT_ID"),
    location="us-central1",
    temperature=0.95,  # Strict temperature
    top_p=0.95,
)


def _call_waiter_llm(query: str, lang: str = "en") -> str:
    """Internal: invoke the waiter persona LLM and return its response."""
    system = (
        f"You are a friendly Indian restaurant waiter. Respond in {lang}. "
        "Keep your reply brief (1-2 sentences). "
        "NEVER list food items from your memory. Respond ONLY based on what is natural to say in a restaurant context. "
        "Every time you are asked, provide a completely fresh and unique response. "
        "Be warm and natural. If an order is confirmed or payment mentioned, say 'I have confirmed your order' or 'Payment received'."
    )
    msgs = [SystemMessage(content=system), HumanMessage(content=query)]
    response = _waiter_llm.invoke(msgs)
    return response.content


def _detect_language(text: str) -> str:
    """Detect the language of the waiter's text. Returns code: hi, en, ta, kn."""
    prompt = (
        "Identify the language of the following text. "
        "Return ONLY the language code: 'hi' for Hindi, 'en' for English, 'kn' for Kannada, 'ta' for Tamil. "
        "If you are unsure, default to 'en'.\n\n"
        f"Text: {text}"
    )
    # Using the same waiter LLM for detection as it's a simple task
    response = _waiter_llm.invoke([HumanMessage(content=prompt)])
    code = response.content.strip().lower()
    # Basic validation
    if code in ["hi", "en", "kn", "ta"]:
        return code
    return "en"


def _extract_food_items(waiter_reply: str) -> List[str]:
    """Pull known food keywords from the waiter reply."""
    known = [
        "pizza", "burger", "pasta", "biryani", "dosa", "sandwich",
        "noodles", "rice", "roti", "idli", "vada", "thali", "salad",
        "soup", "curry", "kebab", "wrap", "paratha", "paneer", "chicken",
    ]
    reply_lower = waiter_reply.lower()
    found = [item for item in known if item in reply_lower]
    if not found:
        # Fallback extraction: grab comma-separated capitalised words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', waiter_reply)
        found = [w.lower() for w in words if w.lower() not in
                 {"the", "and", "our", "for", "are", "you", "have", "with",
                  "that", "this", "from", "your", "also", "very", "some",
                  "today", "available", "would", "like", "what", "can"}][:6]
    return list(dict.fromkeys(found))[:6]  # deduplicate, max 6


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def ask_user(question: str) -> str:
    """Ask the user a clarifying question to gather missing information."""
    return f"ASK_USER: {question}"


@tool
def update_order(key: str, value: str) -> str:
    """Update a specific field in the ongoing order/booking details.
    e.g. key='food_type', value='pizza' or key='quantity', value='2'."""
    return f"ORDER_UPDATED: {key}={value}"


@tool
def query_waiter(message: str, current_waiter_lang: str = "en") -> str:
    """Simulate a conversation with a restaurant waiter.
    Use this to talk to the waiter persona. The waiter responds naturally
    in the requested language. Use the returned information to update the user."""
    print(f"[DEBUG] Tool: query_waiter called with: {message} ({current_waiter_lang})")
    waiter_reply = _call_waiter_llm(message, current_waiter_lang)
    food_items = _extract_food_items(waiter_reply)
    detected_lang = _detect_language(waiter_reply)
    result = {
        "waiter_says": waiter_reply,
        "food_options": food_items,
        "detected_lang": detected_lang,
    }
    dump = json.dumps(result)
    print(f"[DEBUG] Tool: query_waiter result: {dump}")
    return f"WAITER_REPLY: {dump}"


@tool
def complete_service() -> str:
    """Finalize the service request. Call this when the waiter has confirmed
    and the user is satisfied. This signals the frontend success animation."""
    return "WORK_DONE: Service request completed successfully!"


tools = [ask_user, update_order, query_waiter, complete_service]
tool_node = ToolNode(tools)

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

llm = ChatVertexAI(
    model_name="gemini-2.0-flash-001",
    project=os.getenv("GOOGLE_PROJECT_ID"),
    location="us-central1",
    temperature=0.95,  # Strict temperature
    top_p=0.95,
).bind_tools(tools)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def build_system_prompt(state: AgentState) -> str:
    waiter_mode = state.get("waiter_mode_active", False)
    return (
        "You are the AGENT (Mediator AI). You facilitate interaction between a PROVIDER (Waiter) and a USER (Deaf Person).\n\n"
        "STRICT UNBREAKABLE RULES:\n"
        "1. DYNAMIC LANGUAGE: You MUST respond to the PROVIDER in exactly the same language they used (Current: {waiter_lang}).\n"
        "2. DUAL RESPONSE FORMAT: You MUST provide your response in EXACTLY this schema every time:\n"
        "   PROVIDER_REPLY: [Your direct reply back to the waiter in {waiter_lang}]\n"
        "   DEAF_SUMMARY: [Simple English summary of the waiter's info for the deaf user]\n\n"
        "3. NO HALLUCINATION: You can ONLY summarize or repeat what the PROVIDER just said. NEVER add or remember items from your own knowledge.\n"
        "4. 3-ENTITY FLOW:\n"
        "   - If PROVIDER lists foods (e.g., 'idli, tea'), DEAF_SUMMARY must include [[SHOW_PLACEHOLDER_IMAGES: idli, tea]].\n"
        "   - If USER selects an item (e.g., 'idli'), PROVIDER_REPLY must ask the waiter: 'The customer wants to order [item]. What is the price? How long will it take?' (In {waiter_lang}).\n"
        "5. FIRST TURN: If no waiter speech yet, PROVIDER_REPLY must be: 'What food items do you have available?' (Translated to {waiter_lang}).\n\n"
        "THINK STEP-BY-STEP EVERY TIME:\n"
        "Step 1: What is the latest input (Speech or Selection)?\n"
        "Step 2: What is the detected language ({waiter_lang})?\n"
        "Step 3: Generate PROVIDER_REPLY in {waiter_lang} and DEAF_SUMMARY + signals in English.\n"
        "Step 4: Do NOT invent anything.\n\n"
        "CONTEXT:\n"
        "- Waiter Language: {waiter_lang}\n"
        "- Order Details: {details}"
    ).format(
        waiter_lang=state.get("waiter_lang", "en"),
        details=json.dumps(state.get("order_details", {})),
    )


def call_model(state: AgentState) -> dict:
    messages = state["messages"]
    system_prompt = build_system_prompt(state)
    print(f"[DEBUG] [AGENT] Constructing prompt. Waiter Mode: {state.get('waiter_mode_active')}")
    full_messages: List[BaseMessage] = [SystemMessage(content=system_prompt)] + list(messages)
    response = llm.invoke(full_messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def process_tool_results(state: AgentState) -> dict:
    messages = state["messages"]
    order_details = dict(state.get("order_details", {}))
    is_done = state.get("is_done", False)
    food_options = list(state.get("food_options", []))
    waiter_lang = state.get("waiter_lang", "en")

    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content or ""
            if content.startswith("ORDER_UPDATED:"):
                try:
                    kv = content.replace("ORDER_UPDATED:", "").strip()
                    k, v = kv.split("=", 1)
                    order_details[k.strip()] = v.strip()
                except ValueError:
                    pass
            if content.startswith("WAITER_REPLY:"):
                try:
                    raw = content.replace("WAITER_REPLY:", "").strip()
                    parsed = json.loads(raw)
                    food_options = parsed.get("food_options", food_options)
                    waiter_lang = parsed.get("detected_lang", waiter_lang)
                except (json.JSONDecodeError, KeyError):
                    pass
            if "WORK_DONE" in content:
                is_done = True

    return {
        "order_details": order_details,
        "is_done": is_done,
        "food_options": food_options,
        "waiter_lang": waiter_lang,
    }


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_node("process_tool_results", process_tool_results)

workflow.set_entry_point("agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {"tools": "tools", END: END},
)
workflow.add_edge("tools", "process_tool_results")
workflow.add_edge("process_tool_results", "agent")

memory = MemorySaver()
compiled_graph = workflow.compile(checkpointer=memory)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

_session_store: Dict[str, dict] = {}


def get_or_create_agent(session_id: str, lang: str = "hi") -> "GraphAgent":
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
        }
    return GraphAgent(session_id, lang)


class GraphAgent:
    def __init__(self, session_id: str, lang: str = "hi"):
        self.session_id = session_id
        self.lang = lang
        self.config = {"configurable": {"thread_id": session_id}}

    async def get_response(
        self,
        user_input: str,
        detected_intent: str,
        detected_details: Dict[str, Any],
        lang: str = "hi",
        session_id: str = "",
        action: str = None,
        waiter_lang: str = "en"
    ) -> tuple:
        session_state = _session_store.get(self.session_id, {})
        current_service = session_state.get("current_service", "food_order")
        waiter_mode_active = session_state.get("waiter_mode_active", False)

        input_state: dict = {
            "messages": [],
            "lang": lang,
        }

        if action == "speak_to_waiter":
            waiter_mode_active = True
            input_state["waiter_mode_active"] = True
            input_state["waiter_lang"] = waiter_lang
            input_state["messages"].append(HumanMessage(content=f"Action: [START_WAITER_CONVERSATION]. Detected Lang: {waiter_lang}. Respond according to rule 5."))
            if self.session_id in _session_store:
                _session_store[self.session_id]["waiter_mode_active"] = True
                _session_store[self.session_id]["waiter_lang"] = waiter_lang
        elif user_input:
            # FIX Mission: Update language per turn
            input_state["waiter_lang"] = waiter_lang
            if self.session_id in _session_store:
                _session_store[self.session_id]["waiter_lang"] = waiter_lang
            input_state["messages"].append(HumanMessage(content=user_input))

        print(f"[DEBUG] [AGENT] ainvoke start ({self.session_id}). Waiter Mode: {waiter_mode_active}")
        result = await compiled_graph.ainvoke(input_state, self.config)
        print(f"[DEBUG] [AGENT] ainvoke end ({self.session_id}). New messages: {len(result['messages'])}")

        # Extract final AI response
        final_response = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and msg.content:
                final_response = msg.content
                break

        is_done = result.get("is_done", False)
        food_options: List[str] = result.get("food_options", [])
        waiter_lang: str = result.get("waiter_lang", "en")

        # Check tool messages
        for msg in result["messages"]:
            if isinstance(msg, ToolMessage):
                c = msg.content or ""
                if "WORK_DONE" in c:
                    is_done = True
                if c.startswith("WAITER_REPLY:"):
                    try:
                        parsed = json.loads(c.replace("WAITER_REPLY:", "").strip())
                        food_options = parsed.get("food_options", food_options)
                        waiter_lang = parsed.get("detected_lang", waiter_lang)
                    except (json.JSONDecodeError, KeyError):
                        pass

        show_match = re.search(r'SHOW_FOODS:\s*(\[.*?\])', final_response)
        if show_match:
            try:
                food_options = json.loads(show_match.group(1))
            except json.JSONDecodeError:
                pass
            final_response = re.sub(r'SHOW_FOODS:\s*\[.*?\]', '', final_response).strip()

        # Signal for Speak to Waiter button via tag
        signal = None
        if "[[SHOW_WAITER_BUTTON]]" in final_response:
            signal = "SHOW_WAITER_BUTTON"
            final_response = final_response.replace("[[SHOW_WAITER_BUTTON]]", "").strip()
        elif waiter_mode_active and not is_done:
            signal = "WAITER_ACTIVE"

        if is_done and "WORK_DONE" not in final_response:
            final_response += " WORK_DONE"

        # Persistence check for signal if tag not present (fallback)
        if not signal and "check the menu with the waiter" in final_response.lower() and not waiter_mode_active:
            signal = "SHOW_WAITER_BUTTON"

        if self.session_id in _session_store:
            _session_store[self.session_id]["order_details"] = result.get(
                "order_details", _session_store[self.session_id]["order_details"]
            )
            _session_store[self.session_id]["is_done"] = is_done
            _session_store[self.session_id]["food_options"] = food_options
            _session_store[self.session_id]["waiter_lang"] = waiter_lang

        status = "done" if is_done else "pending"
        return final_response, status, food_options, waiter_lang, signal
