# Testing Guide for 3-Entity Agentic Orchestration

## What Was Changed

### Backend (Complete Rewrite)

1. **`backend/agents/service_agent.py`** - Completely rewritten with:
   - Strict 3-entity architecture (USER, PROVIDER, AGENT)
   - Language detection using `langdetect` (detect per provider message)
   - Food item parsing with Gemini (temperature=0.95)
   - Structured output format (PROVIDER_REPLY, USER_SUMMARY, SIGNAL)
   - No role-playing, no hallucination - only relays actual provider speech
   - Session-based state management with waiter language tracking

2. **`backend/main.py`** - Updated WebSocket handler:
   - Continuous loop for message processing
   - Three distinct action handlers:
     - `speak_to_waiter`: Starts conversation mode
     - `user_selection`: Handles food item selection
     - Provider speech: Detects language, parses items, processes
   - Updated `_build_response()` for new signal structure

### Frontend (Enhanced)

1. **`frontend/src/App.tsx`** - Major updates:
   - Placeholder image grid for food items
   - Agent speaking state management
   - ORDER_DONE signal handling with .glb animation trigger
   - Mic visual states (pulsing when listening, paused when agent speaks)
   - Image selection handler

2. **`frontend/src/components/VoiceControls.tsx`**:
   - Added `agentSpeaking` prop support
   - Visual state for agent speaking (grayed mic icon)
   - Updated hints and styling

3. **`frontend/src/components/ISLAvatar.tsx`**:
   - Support for .glb files (not just .gltf)
   - Special handling for `order_done.glb` animation
   - Longer playback duration for success animation

## Test Flow

### Required Test Case (Must Pass)

**Scenario**: User orders food using ISL, waiter speaks Hindi, order confirmed

1. **User Action**: Sign "hungry" or "eat" → Backend detects `food_order` intent
   - **Expected**: Agent replies in English: "I understand you're hungry. Press Speak to Waiter to check the menu."
   - **Expected**: "Speak to Waiter" button appears

2. **User Action**: Press "Speak to Waiter" button
   - **Expected**: Waiter mode activates
   - **Expected**: Pulsing mic icon appears (red, "Listening to Waiter...")
   - **Expected**: Agent asks provider (in English by default): "What food items do you have available today?"

3. **Provider Action**: Speak in Hindi: "हमारे पास इडली और चाय है"
   - **Expected**: Language detected as 'hi'
   - **Expected**: Food items parsed: ["idli", "tea"] or ["इडली", "चाय"]
   - **Expected**: Placeholder images appear (clickable cards with "idli" and "tea")
   - **Expected**: User sees English summary: "Provider says idli and tea are available. Please select one."
   - **Expected**: Provider hears TTS in Hindi (acknowledgment)

4. **User Action**: Click on "idli" image
   - **Expected**: Images disappear
   - **Expected**: Chat shows "🍽️ Selected: idli"
   - **Expected**: Agent asks provider in Hindi: "ग्राहक इडली ऑर्डर करना चाहते हैं। कीमत क्या है? कितना समय लगेगा?"
   - **Expected**: Mic visual shows "Agent speaking..." (grayed out, paused state)

5. **Provider Action**: Speak in Hindi: "₹50, 10 मिनट"
   - **Expected**: Language still 'hi'
   - **Expected**: User sees English summary: "Provider says ₹50, ready in 10 minutes. Shall I confirm your order?"
   - **Expected**: Mic returns to pulsing state (listening)

6. **Provider Action**: Speak "order accepted" or "confirmed" or "payment received"
   - **Expected**: Signal: ORDER_DONE
   - **Expected**: Mic stops (waiterActive = false)
   - **Expected**: ISL Avatar plays `order_done.glb` animation (if file exists)
   - **Expected**: Success card appears with "Service Completed!"

## Quick Test Commands

### Start Backend
```bash
cd backend
uv run python -m uvicorn main:app --reload --port 8080
```

### Start Frontend
```bash
cd frontend
npm run dev
```

## Key Architecture Points

### Unbreakable Rules (Temperature = 0.95 Always)
- Agent NEVER role-plays as provider
- Agent NEVER invents food items, prices, or times
- Agent ONLY uses information from provider's CURRENT message
- Provider language detected per turn and stored
- User summaries ALWAYS in English
- Provider replies ALWAYS in detected provider language

### Signal Flow
- `NONE`: No special action
- `SHOW_PLACEHOLDER_IMAGES`: Display clickable food images
- `ORDER_DONE`: Play success animation, pause mic, show completion

### State Management
- `waiter_lang`: Updated every provider message
- `food_options`: Parsed from provider speech
- `selected_item`: User's choice
- `last_provider_message`: For completion keyword detection

## Troubleshooting

### Images don't appear
- Check if `SHOW_PLACEHOLDER_IMAGES` signal is sent
- Verify food items are parsed correctly in backend logs
- Check browser console for payload inspection

### Language not detected
- Ensure provider speech is at least 3 characters
- Check backend logs for `[LANG_DETECT]` output
- Verify langdetect is installed: `uv pip list | grep langdetect`

### ORDER_DONE not triggering
- Check if provider said exact keywords: "order accepted", "confirmed", "payment received"
- Inspect `last_provider_message` in session state
- Look for `[AGENT] Response generated - Signal: ORDER_DONE` in backend logs

### .glb animation not playing
- Ensure file exists at: `frontend/public/models/order_done.glb`
- Check browser console for Three.js errors
- Verify ISLAvatar component receives 'order_done' in responseSequence

## Expected Log Output

### Backend (Successful Flow)
```
[WS] Connected: session-xyz
[WS] Action: speak_to_waiter
[AGENT] Processing request for session session-xyz
[AGENT] Invoking LLM with 1 messages
[WS] Waiter speech: हमारे पास इडली और चाय है
[WS] Detected language: hi
[LANG_DETECT] Detected: hi
[FOOD_PARSE] Extracted items: ['idli', 'tea']
[AGENT] Response generated - Signal: SHOW_PLACEHOLDER_IMAGES, Items: ['idli', 'tea']
[WS] Sent to client with signal: SHOW_PLACEHOLDER_IMAGES
[WS] Action: user_selection - item: idli
[AGENT] Processing request for session session-xyz
[WS] Waiter speech: order accepted
[AGENT] Response generated - Signal: ORDER_DONE, Items: []
[WS] Sent to client with signal: ORDER_DONE
```

### Frontend (Browser Console)
```
[STT] Result: हमारे पास इडली और चाय है
WebSocket received: {signal: "SHOW_PLACEHOLDER_IMAGES", items: ["idli", "tea"], ...}
User clicked image: idli
WebSocket sent: {..., action: "user_selection", item: "idli"}
WebSocket received: {signal: "ORDER_DONE", status: "done", ...}
```

## Demo Script

For judge demonstration, follow this exact script:

**Presenter**: "Watch as our deaf user orders food using Indian Sign Language."

1. Show user signing "hungry" → Agent detects intent
2. Click "Speak to Waiter" → Mic starts pulsing (RED)
3. Speak in Hindi: "हमारे पास इडली, चाय और कॉफी है"
4. Images appear → Click "idli"
5. Agent asks in Hindi (shows on screen + TTS plays)
6. Speak: "₹50, 10 मिनट" → English summary appears for user
7. Speak: "order confirmed" → Success animation plays, mic stops

**Key Points to Highlight**:
- Real-time language detection (Hindi → English)
- No hardcoded menus (only uses what waiter said)
- Visual feedback (mic states, images, animations)
- True 3-entity separation (agent mediates, never role-plays)
- Accessible for deaf users (English summaries, visual cues)
