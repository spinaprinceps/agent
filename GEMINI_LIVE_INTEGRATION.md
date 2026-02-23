# Gemini Live Integration Guide

## Backend Setup

### 1. Install Dependencies
```bash
cd backend
uv add websockets
```

### 2. Add GOOGLE_API_KEY to .env
```bash
# backend/.env
GOOGLE_API_KEY=your_api_key_here
GOOGLE_PROJECT_ID=project-094185f3-8549-4a5d-890
```

**CRITICAL:** You need a Google API key (not just project ID) for Gemini Live API.
Get it from: https://aistudio.google.com/app/apikey

### 3. Start Backend
```bash
cd backend
uv run uvicorn main:app --reload --port 8080
```

---

## Frontend Integration

### 1. Import Component in App.tsx
```tsx
import GeminiLiveVoice from './components/GeminiLiveVoice';
```

### 2. Add State for Gemini Live Mode
```tsx
const [useGeminiLive, setUseGeminiLive] = useState(true); // Toggle for new vs old system
```

### 3. Add Component to JSX (Replace VoiceControls)
```tsx
{useGeminiLive ? (
  <GeminiLiveVoice
    sessionId={sessionId}
    onFoodImages={(items, summary) => {
      console.log('[GEMINI_LIVE] Food images:', items);
      setPlaceholderImages(items);
      setHistory(prev => [...prev, {
        role: 'agent',
        text: summary,
        timestamp: new Date()
      }]);
    }}
    onOrderConfirmed={(summary) => {
      console.log('[GEMINI_LIVE] Order confirmed:', summary);
      setServiceStatus('done');
      setHistory(prev => [...prev, {
        role: 'agent',
        text: summary,
        timestamp: new Date()
      }]);
      // Trigger .glb animation here
      // setShowSuccessAnimation(true);
    }}
    onAgentSpeaking={(speaking) => {
      setAgentSpeaking(speaking);
    }}
  />
) : (
  <VoiceControls
    // ... existing props
  />
)}
```

### 4. Wire ISL Video to Gemini Live
When user records ISL video, send text interpretation to Gemini:

```tsx
const handleISLVideoResult = (analysis: any) => {
  const userText = analysis.text; // e.g., "hungry", "food order"
  
  if (useGeminiLive) {
    // Send to Gemini Live via window API
    (window as any).geminiLiveVoice?.sendText(userText);
  } else {
    // Use old WebSocket system
    sendWsMessage({ type: 'isl_input', text: userText });
  }
};
```

### 5. Wire Food Selection to Gemini Live
When user clicks on food image:

```tsx
const handleFoodClick = (item: string) => {
  console.log('[App] User selected food:', item);
  
  if (useGeminiLive) {
    (window as any).geminiLiveVoice?.sendUserSelection(item);
  } else {
    // Use old system
    sendWsMessage({ type: 'user_selection', selected_item: item });
  }
};
```

### 6. Order Confirmation
When user confirms order (e.g., clicks "Confirm" button):

```tsx
const handleConfirmOrder = () => {
  if (useGeminiLive) {
    (window as any).geminiLiveVoice?.sendUserConfirmation();
  } else {
    // Use old system
    sendWsMessage({ type: 'user_confirmation' });
  }
};
```

---

## Testing Flow

### Complete End-to-End Test:

1. **Start backend** with GOOGLE_API_KEY set
2. **Start frontend** with `npm run dev`
3. **Open browser** to http://localhost:5173
4. **Test sequence:**
   - User signs "hungry" via webcam
   - Backend analyzes ISL → sends "hungry" text to Gemini
   - Gemini (agent) speaks to provider: "Hello! What food items do you have?"
   - **Provider speaks** (into mic): "We have idli, tea, coffee"
   - Gemini detects language (Hindi/English)
   - Gemini calls `show_food_images(["idli", "tea", "coffee"], "Provider has idli, tea, coffee")`
   - Frontend shows 3 food images + English summary
   - **User clicks "idli"**
   - Function called: `user_selected_item("idli", "hi")`
   - Gemini asks provider in Hindi: "What is the price and time for idli?"
   - **Provider responds** in Hindi: "30 rupees, 10 minutes"
   - Gemini updates summary to user
   - **User confirms** (clicks confirm button)
   - Gemini tells provider: "Customer confirms. Please prepare."
   - **Provider says** "okay/confirmed"
   - Gemini calls `order_confirmed("Order confirmed: 1 idli, ₹30, 10 minutes")`
   - Frontend triggers ORDER_DONE animation (.glb)

---

## Audio Technical Details

### Input (Microphone → Gemini):
- **Format:** 16kHz mono PCM (16-bit signed int)
- **Capture:** ScriptProcessorNode (4096 samples per chunk)
- **Encoding:** Int16Array → Base64 → WebSocket
- **Echo cancellation:** Enabled via getUserMedia constraints
- **Auto-pause:** Mic pauses when agent is speaking (echo prevention)

### Output (Gemini → Speaker):
- **Format:** 24kHz mono PCM (16-bit signed int)
- **Queue:** FIFO queue to prevent choppy playback
- **Decoding:** Base64 → Int16Array → Float32Array
- **Playback:** Web Audio API (AudioContext + BufferSource)
- **Voice:** Aoede (female, natural, multilingual)

---

## Key Differences from Old System

| Feature | Old System | Gemini Live |
|---------|-----------|-------------|
| **Architecture** | Custom LangGraph agent + STT + TTS | Native Gemini multimodal |
| **Latency** | ~2-3 seconds | ~400-600ms |
| **Voice Quality** | Google Cloud TTS | Gemini native voice (better) |
| **Language Switch** | Manual detection + translate | Auto-detect + native |
| **Interruption** | Not supported | Natural turn-taking |
| **Bidirectional** | No (one-way) | Yes (true conversation) |
| **Function Calling** | Custom parsing | Native Gemini tools |
| **Conversation State** | LangGraph checkpointer | Gemini session memory |

---

## Troubleshooting

### "GOOGLE_API_KEY not configured"
- Add API key to backend/.env
- Restart uvicorn

### No audio playback
- Check browser console for AudioContext errors
- Ensure HTTPS or localhost (required for getUserMedia)
- Check speaker/volume settings

### Mic not working
- Grant microphone permissions in browser
- Check browser console for getUserMedia errors
- Try different browser (Chrome recommended)

### Agent not responding
- Check backend terminal for "[GEMINI_LIVE]" logs
- Verify WebSocket connection (should see "Connected to Gemini Live API")
- Check network tab in browser DevTools

### Wrong language
- System auto-detects from provider's speech
- If wrong, provider should speak more clearly
- Check system prompt configuration

---

## Production Deployment

### Security:
- **DO NOT** expose GOOGLE_API_KEY in frontend
- Keep WebSocket proxy in backend
- Add rate limiting to prevent abuse
- Implement authentication for WebSocket connections

### Performance:
- Use Redis for session state (if multiple backend instances)
- Enable gzip compression for WebSocket messages
- Monitor Gemini API quotas/costs
- Implement reconnection logic with exponential backoff

### Monitoring:
- Log all Gemini API errors
- Track audio quality metrics (packet loss, latency)
- Monitor WebSocket connection stability
- Alert on high error rates

---

## Cost Estimate

Gemini 2.0 Flash pricing (as of Feb 2026):
- **Audio input:** ~$0.30 per hour
- **Audio output:** ~$0.60 per hour
- **Function calling:** Included

Example 5-minute food order:
- Input: $0.025
- Output: $0.050
- **Total: ~$0.075 per order**

Significantly cheaper than separate STT + LLM + TTS pipeline.
