import React, { useState, useEffect, useCallback, useRef } from 'react';
import WebcamCapture from './components/WebcamCapture';
import ISLAvatar from './components/ISLAvatar';
import VoiceControls from './components/VoiceControls';
import FoodSelection from './components/FoodSelection';
import { Mic } from 'lucide-react';

interface ChatMessage {
    role: 'user' | 'agent' | 'provider';
    text: string;
    timestamp: Date;
    lang?: string;
}

const App: React.FC = () => {
    const [sessionId] = useState(`session-${Math.random().toString(36).substr(2, 9)}`);
    const [lang, setLang] = useState('hi');
    const [islResponse, setIslResponse] = useState<string[]>([]);
    const [history, setHistory] = useState<ChatMessage[]>([]);
    const [ws, setWs] = useState<WebSocket | null>(null);
    const [wsConnected, setWsConnected] = useState(false);
    const [serviceStatus, setServiceStatus] = useState<'idle' | 'processing' | 'done'>('idle');
    const [foodOptions, setFoodOptions] = useState<string[]>([]);
    const [showWaiterButton, setShowWaiterButton] = useState(false);
    const [waiterActive, setWaiterActive] = useState(false);
    const [waiterLang, setWaiterLang] = useState('hi');
    const [placeholderImages, setPlaceholderImages] = useState<string[]>([]);
    const [agentSpeaking, setAgentSpeaking] = useState(false);
    const chatEndRef = useRef<HTMLDivElement>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    // Load speech synthesis voices
    useEffect(() => {
        if (window.speechSynthesis) {
            // Load voices (they may not be ready immediately)
            window.speechSynthesis.getVoices();
            window.speechSynthesis.onvoiceschanged = () => {
                const voices = window.speechSynthesis.getVoices();
                console.log('[TTS] Voices loaded:', voices.length);
            };
        }
    }, []);

    // Auto-scroll chat
    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [history]);

    // WebSocket setup with auto-reconnect
    useEffect(() => {
        console.log('[WS] ======== WebSocket initialization (with reconnect) ========');
        console.log('[WS] Session ID:', sessionId);

        let cancelled = false;
        let backoff = 500; // ms

        const connect = () => {
            if (cancelled) return;
            console.log('[WS] Attempting websocket connection... backoff=', backoff);
            const socket = new WebSocket(`ws://localhost:8080/ws/${sessionId}`);

            socket.onopen = () => {
                console.log('[WS] ✓✓✓ CONNECTED ✓✓✓');
                console.log('[WS] ReadyState:', socket.readyState, '(1=OPEN)');
                setWs(socket);
                setWsConnected(true);
                backoff = 500; // reset
            };

            socket.onclose = (event) => {
                console.log('[WS] ❌❌❌ CLOSED ❌❌❌');
                console.log('[WS] Code:', event.code);
                console.log('[WS] Reason:', event.reason || 'No reason provided');
                console.log('[WS] Clean:', event.wasClean);
                setWsConnected(false);
                setWs(null);
                if (!cancelled) {
                    // exponential backoff up to 5s
                    setTimeout(() => {
                        backoff = Math.min(5000, backoff * 2);
                        connect();
                    }, backoff);
                }
            };

            socket.onerror = (error) => {
                console.error('[WS] ✗✗✗ ERROR ✗✗✗', error);
                console.log('[WS] ReadyState:', socket.readyState);
                setWsConnected(false);
            };

            socket.onmessage = (event) => {
                // Handle payloads (attempt to parse JSON)
                try {
                    const data = JSON.parse(event.data);
                    handleServerPayload(data);
                } catch (parseError) {
                    console.error('[WS] ✗ JSON parse error:', parseError);
                }
            };
        };

        connect();

        return () => {
            cancelled = true;
            console.log('[WS] ======== Cleanup: closing socket ========');
            ws?.close();
            setWs(null);
        };
    }, [sessionId]);

    // ---------- Payload handler (shared by HTTP + WS) ----------
    const handleServerPayload = useCallback((data: any) => {
        console.log('[App.handleServerPayload] ========================================');
        console.log('[App.handleServerPayload] Received from backend:', data);
        const botText: string = data.bot_response || '';
        const providerReply: string = data.bot_response_to_provider || '';
        const userSummary: string = data.user_summary || botText;
        const signal: string = data.signal || '';
        const items: string[] = data.items || [];
        const options: string[] = data.food_options || [];
        const voiceAudio: string | undefined = data.voice_audio;
        const waiterLang: string = data.waiter_lang || 'hi';
        console.log('[App.handleServerPayload] Extracted:');
        console.log('  - providerReply:', providerReply);
        console.log('  - userSummary:', userSummary);
        console.log('  - signal:', signal);
        console.log('  - voiceAudio:', voiceAudio ? `${voiceAudio.length} chars` : 'none');
        console.log('  - waiterLang:', waiterLang);

        // Keep waiterLang in sync
        if (data.waiter_lang) setWaiterLang(data.waiter_lang);

        // Update chat: Use English summary for the user
        if (userSummary) {
            const cleanText = userSummary.replace('WORK_DONE', '').trim();
            setHistory(prev => [...prev, {
                role: 'agent',
                text: cleanText,
                timestamp: new Date(),
                lang: 'en', // User summary is always English
            }]);

            // Map words to ISL clips
            const words = cleanText.toLowerCase().replace(/[.,!?]/g, '').split(' ').slice(0, 6);
            setIslResponse(words);
        }

        // Handle signals
        console.log('[handleServerPayload] Received signal:', signal);
        
        if (signal === 'SHOW_WAITER_BUTTON' || signal === 'SHOW_PROVIDER_BUTTON') {
            console.log('[handleServerPayload] Showing provider button');
            setShowWaiterButton(true);
            setWaiterActive(false);
            setPlaceholderImages([]);
            setFoodOptions([]);
        }
        
        if (signal === 'WAITER_ACTIVE') {
            console.log('[handleServerPayload] Activating waiter mode');
            setWaiterActive(true);
            setShowWaiterButton(false);
        }
        
        if (signal === 'SHOW_PLACEHOLDER_IMAGES') {
            const finalItems = items.length > 0 ? items : options;
            setPlaceholderImages(finalItems);
            setFoodOptions([]);
            setShowWaiterButton(false);
            setWaiterActive(true);
            setAgentSpeaking(false);
        }
        
        if (signal === 'SHOW_FOODS' || signal === 'SHOW_MENU_IMAGES') {
            const finalOptions = items.length > 0 ? items : options;
            setFoodOptions(finalOptions);
            setPlaceholderImages([]);
            setShowWaiterButton(false);
            setWaiterActive(true);
        }
        
        if (signal === 'ORDER_DONE' || signal === 'WORK_DONE' || data.status === 'done') {
            setServiceStatus('done');
            setIslResponse(['order_done']); // Trigger order_done.glb animation
            setFoodOptions([]);
            setPlaceholderImages([]);
            setShowWaiterButton(false);
            setWaiterActive(false);
            setAgentSpeaking(false);
        }

        // Agent speaking state (pause mic visually)
        if (providerReply && providerReply.trim() && providerReply !== '[NONE]' && signal !== 'ORDER_DONE') {
            setAgentSpeaking(true);
            
            // Add agent's question to provider in chat (only if different from user summary)
            if (providerReply !== userSummary) {
                setHistory(prev => [...prev, {
                    role: 'agent',
                    text: `🗣️ Agent to Provider: ${providerReply}`,
                    timestamp: new Date(),
                    lang: waiterLang,
                }]);
            }
            // agentSpeaking is cleared in playBase64Audio().onended / utterance.onend below
        }

        // Play TTS: Use Provider Reply in their detected language (only if not empty/none)
        console.log('[App.handleServerPayload] TTS decision:');
        console.log('  - Has voiceAudio?', !!voiceAudio);
        console.log('  - providerReply valid?', providerReply && providerReply !== '[NONE]');
        if (voiceAudio && providerReply && providerReply !== '[NONE]') {
            console.log('[TTS] ✓ Playing Google TTS audio from server');
            playBase64Audio(voiceAudio);
        } else if (providerReply && providerReply.trim() && providerReply !== '[NONE]') {
            console.log('[TTS] ✓ Using browser TTS fallback for:', providerReply.substring(0, 50));
            const clean = providerReply.replace('WORK_DONE', '').trim();
            const utterance = new SpeechSynthesisUtterance(clean);
            // Try to match the language with female voice preference
            const langMap: Record<string, string> = {
                'hi': 'hi-IN',
                'en': 'en-US',
                'kn': 'kn-IN',
                'ta': 'ta-IN'
            };
            utterance.lang = langMap[waiterLang] || 'en-US';

            const voices = window.speechSynthesis.getVoices();
            const femaleVoice = voices.find(v =>
                v.lang.startsWith(utterance.lang.split('-')[0]) &&
                (v.name.toLowerCase().includes('female') || 
                 v.name.toLowerCase().includes('google') ||
                 v.name.toLowerCase().includes('samantha') ||
                 v.name.toLowerCase().includes('zira'))
            );
            if (femaleVoice) {
                console.log('[TTS] Using female voice:', femaleVoice.name);
                utterance.voice = femaleVoice;
            } else {
                console.log('[TTS] No female voice found, using default');
            }
            utterance.pitch = 1.1; // Slightly higher pitch for female voice
            utterance.onend = () => {
                console.log('[TTS] Browser TTS finished — resuming mic');
                setAgentSpeaking(false);
            };
            utterance.onerror = () => setAgentSpeaking(false);
            window.speechSynthesis.speak(utterance);
        }
    }, [lang]);

    const playBase64Audio = (b64: string) => {
        try {
            console.log('[Audio] Decoding base64 audio, length:', b64.length);
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
            const blob = new Blob([bytes], { type: 'audio/mp3' });
            const url = URL.createObjectURL(blob);
            if (audioRef.current) {
                audioRef.current.src = url;
                audioRef.current.onended = () => {
                    console.log('[Audio] TTS finished — resuming mic');
                    setAgentSpeaking(false);
                    URL.revokeObjectURL(url);
                };
                audioRef.current.play().then(() => {
                    console.log('[Audio] Playing TTS audio successfully');
                }).catch(err => {
                    console.error('[Audio] Play failed:', err);
                    setAgentSpeaking(false); // unblock mic on error
                });
            } else {
                console.error('[Audio] audioRef is null');
                setAgentSpeaking(false);
            }
        } catch (e) {
            console.error('[Audio] Failed to play TTS audio', e);
            setAgentSpeaking(false);
        }
    };

    // ---------- Upload ISL video ----------
    const handleIslUpload = useCallback(async (blob: Blob) => {
        setServiceStatus('processing');
        setShowWaiterButton(false);
        const formData = new FormData();
        formData.append('file', blob, 'recording.webm');
        formData.append('session_id', sessionId);
        formData.append('lang', lang);

        try {
            const res = await fetch('http://localhost:8080/upload-isl-video', {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();

            setHistory(prev => [...prev, {
                role: 'user',
                text: `(Signed): ${data.user_text || 'Unrecognized sign'}`,
                timestamp: new Date(),
            }]);

            handleServerPayload(data);

            // Force button if food_order intent detected (Stage 1)
            if (data.intent === 'food_order' || data.intent === 'hungry') {
                console.log('[Upload] Food order intent detected, ensuring button shows');
                if (data.signal === 'SHOW_WAITER_BUTTON' || data.signal === 'SHOW_PROVIDER_BUTTON') {
                    setShowWaiterButton(true);
                }
            }

            if (data.status !== 'done') {
                setServiceStatus('idle');
            }
        } catch (err) {
            console.error('[Upload error]', err);
            setHistory(prev => [...prev, {
                role: 'agent',
                text: '⚠️ Could not reach the server. Is the backend running?',
                timestamp: new Date(),
            }]);
            setServiceStatus('idle');
        }
    }, [sessionId, lang, handleServerPayload]);

    // ---------- Send WS message ----------
    const sendWsMessage = useCallback((text: string, type = 'text', action?: string, item?: string) => {
        const payload = { text, type, action, item, lang, session_id: sessionId };
        console.log('[App.sendWsMessage] ========================================');
        console.log('[App.sendWsMessage] ▶ Sending message');
        console.log('[App.sendWsMessage] WS state:', ws?.readyState, '(1=OPEN, 0=CONNECTING, 2=CLOSING, 3=CLOSED)');
        console.log('[App.sendWsMessage] Payload:', JSON.stringify(payload));
        console.log('[App.sendWsMessage] Timestamp:', new Date().toISOString());
        if (ws && ws.readyState === WebSocket.OPEN) {
            try {
                ws.send(JSON.stringify(payload));
                console.log('[App.sendWsMessage] ✓✓✓ Sent successfully ✓✓✓');
            } catch (sendError) {
                console.error('[App.sendWsMessage] ✗ Send failed:', sendError);
            }
        } else {
            console.error('[App.sendWsMessage] ✗✗✗ WebSocket not open! State:', ws?.readyState);
            console.error('[App.sendWsMessage] Cannot send message - connection issue!');
        }
        console.log('[App.sendWsMessage] ========================================');
    }, [ws, lang, sessionId]);

    // ---------- Actions ----------
    const handleSpeakToWaiter = () => {
        setShowWaiterButton(false);
        setWaiterActive(true); // Immediately activate to show mic
        setHistory(prev => [...prev, {
            role: 'user',
            text: '👆 Interaction: Speak to Provider',
            timestamp: new Date(),
        }]);
        sendWsMessage('', 'action', 'speak_to_waiter');
    };

    // ---------- Voice controls (provider interface) ----------
    const handleVoiceMessage = useCallback((text: string) => {
        console.log('[App.handleVoiceMessage] ========================================');
        console.log('[App.handleVoiceMessage] Provider said:', text);
        setHistory(prev => [...prev, {
            role: 'provider',
            text,
            timestamp: new Date(),
        }]);
        console.log('[App.handleVoiceMessage] Sending via WebSocket...');
        sendWsMessage(text);
        console.log('[App.handleVoiceMessage] ========================================');
    }, [sendWsMessage]);

    // ---------- Food selection ----------
    const handleFoodSelect = useCallback((food: string) => {
        setFoodOptions([]);
        setPlaceholderImages([]);
        setHistory(prev => [...prev, {
            role: 'user',
            text: `🍽️ Selected: ${food}`,
            timestamp: new Date(),
        }]);
        sendWsMessage('', 'selection', 'user_selection', food);
    }, [sendWsMessage]);

    // ---------- Placeholder image selection ----------
    const handleImageSelect = useCallback((item: string) => {
        setPlaceholderImages([]);
        setHistory(prev => [...prev, {
            role: 'user',
            text: `🍽️ Selected: ${item}`,
            timestamp: new Date(),
        }]);
        sendWsMessage('', 'selection', 'user_selection', item);
    }, [sendWsMessage]);

    const handleReset = () => {
        setServiceStatus('idle');
        setIslResponse([]);
        setHistory([]);
        setFoodOptions([]);
        setPlaceholderImages([]);
        setShowWaiterButton(false);
        setAgentSpeaking(false);
    };

    const formatTime = (d: Date) =>
        d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    return (
        <div className="app">
            {/* Hidden audio element for TTS playback */}
            <audio ref={audioRef} style={{ display: 'none' }} />

            {/* Header */}
            <header className="header">
                <div className="header-left">
                    <div className="logo">🤟</div>
                    <div>
                        <h1 className="header-title">ISL Service Assistant</h1>
                        <p className="header-sub">Indian Sign Language → AI Agent</p>
                    </div>
                </div>
                <div className="header-right">
                    <div className={`ws-badge ${wsConnected ? 'connected' : 'disconnected'}`}>
                        <span className="ws-dot" />
                        {wsConnected ? 'Live' : 'Offline'}
                    </div>
                    <select
                        className="lang-select"
                        value={lang}
                        onChange={e => setLang(e.target.value)}
                    >
                        <option value="hi">हिंदी</option>
                        <option value="en">English</option>
                        <option value="kn">ಕನ್ನಡ</option>
                        <option value="ta">தமிழ்</option>
                    </select>
                </div>
            </header>

            <main className="main">
                {/* Left Panel */}
                <section className="panel left-panel">
                    <WebcamCapture
                        onUpload={handleIslUpload}
                        isProcessing={serviceStatus === 'processing'}
                    />

                    {waiterActive && (
                        <div className="waiter-indicator">
                            <div className="pulse-mic">
                                <Mic size={24} color="#7c3aed" />
                            </div>
                            <span>{agentSpeaking ? 'Agent speaking...' : 'Provider Mode Active'}</span>
                        </div>
                    )}

                    {/* Mission: Fixed floating mic feedback with speaking state */}
                    {waiterActive && !agentSpeaking && (
                        <div className="fixed-mic-overlay pulsing">
                            <Mic className="mic-icon-pulse" size={24} />
                            <span>Listening to Provider...</span>
                        </div>
                    )}

                    {waiterActive && agentSpeaking && (
                        <div className="fixed-mic-overlay paused">
                            <Mic className="mic-icon-paused" size={24} />
                            <span>Agent speaking...</span>
                        </div>
                    )}

                    {showWaiterButton && (
                        <div className="mediator-action">
                            <button className="btn-waiter" onClick={handleSpeakToWaiter}>
                                🎤 Speak to Provider
                            </button>
                        </div>
                    )}

                    {/* Placeholder image grid - shown when SHOW_PLACEHOLDER_IMAGES signal received */}
                    {placeholderImages.length > 0 && (
                        <div className="placeholder-grid-wrap">
                            <div className="placeholder-title">📋 Available Items (Select One)</div>
                            <div className="placeholder-grid">
                                {placeholderImages.map((item, idx) => (
                                    <div
                                        key={idx}
                                        className="placeholder-card"
                                        onClick={() => handleImageSelect(item)}
                                    >
                                        <img
                                            src={`https://via.placeholder.com/200x150/7c3aed/ffffff?text=${encodeURIComponent(item)}`}
                                            alt={item}
                                            className="placeholder-img"
                                        />
                                        <div className="placeholder-label">{item}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Food selection — shown when SHOW_FOODS signal received */}
                    {foodOptions.length > 0 && (
                        <FoodSelection options={foodOptions} onSelect={handleFoodSelect} />
                    )}

                    {/* Chat history */}
                    <div className="chat-wrap">
                        <div className="chat-title">💬 Conversation</div>
                        <div className="chat-scroll">
                            {history.length === 0 && (
                                <div className="chat-empty">Sign a request or type below to begin…</div>
                            )}
                            {history.map((h: any, i) => (
                                <div key={i} className={`bubble bubble-${h.role}`}>
                                    <div className="bubble-meta">
                                        <span className="bubble-role">
                                            {h.role === 'user' ? '🧏 You' : h.role === 'agent' ? '🤖 Agent' : '📞 Provider'}
                                            {h.lang && h.lang !== lang && (
                                                <span className="bubble-lang-tag">{h.lang.toUpperCase()}</span>
                                            )}
                                        </span>
                                        <span className="bubble-time">{formatTime(h.timestamp)}</span>
                                    </div>
                                    <div className="bubble-text">{h.text}</div>
                                </div>
                            ))}
                            <div ref={chatEndRef} />
                        </div>
                    </div>
                </section>

                {/* Right Panel */}
                <section className="panel right-panel">
                    <div className="avatar-wrap">
                        <ISLAvatar responseSequence={islResponse} />
                    </div>

                    {serviceStatus === 'done' ? (
                        <div className="success-card">
                            <div className="success-icon">🎉</div>
                            <h2 className="success-title">Service Completed!</h2>
                            <p className="success-sub">Your request has been processed successfully.</p>
                            <button className="btn-new" onClick={handleReset}>
                                Start New Request
                            </button>
                        </div>
                    ) : (
                        <VoiceControls
                            onSendMessage={handleVoiceMessage}
                            lang={lang}
                            waiterActive={waiterActive}
                            agentSpeaking={agentSpeaking}
                            waiterLang={waiterLang}
                        />
                    )}
                </section>
            </main>

            <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0f0f1a; color: #e2e2f0; font-family: 'Inter', system-ui, sans-serif; }
        .app { min-height: 100vh; display: flex; flex-direction: column; }

        .header {
          display: flex; justify-content: space-between; align-items: center;
          padding: 14px 28px;
          background: rgba(255,255,255,0.03);
          border-bottom: 1px solid rgba(255,255,255,0.07);
          backdrop-filter: blur(10px);
          position: sticky; top: 0; z-index: 100;
        }
        .header-left { display: flex; align-items: center; gap: 14px; }
        .logo { font-size: 2rem; }
        .header-title { font-size: 1.2rem; font-weight: 800; color: #fff; letter-spacing: -0.3px; }
        .header-sub { font-size: 0.72rem; color: #666; margin-top: 2px; }
        .header-right { display: flex; align-items: center; gap: 14px; }

        .ws-badge {
          display: flex; align-items: center; gap: 7px;
          font-size: 0.75rem; font-weight: 700; letter-spacing: 0.4px;
          padding: 5px 12px; border-radius: 20px;
        }
        .ws-badge.connected { background: rgba(16,185,129,0.15); color: #34d399; }
        .ws-badge.disconnected { background: rgba(239,68,68,0.15); color: #f87171; }
        .ws-dot {
          width: 7px; height: 7px; border-radius: 50%;
          background: currentColor; animation: pulse-dot 2s infinite;
        }
        @keyframes pulse-dot { 0%,100%{opacity:1} 50%{opacity:0.3} }

        .lang-select {
          background: rgba(255,255,255,0.08);
          border: 1px solid rgba(255,255,255,0.12);
          color: #ddd; padding: 6px 12px;
          border-radius: 8px; font-size: 0.85rem;
          cursor: pointer; outline: none;
        }

        .main {
          display: grid; grid-template-columns: 1fr 1fr;
          gap: 24px; padding: 24px 28px;
          flex: 1; max-width: 1400px; margin: 0 auto; width: 100%;
        }
        @media (max-width: 860px) { .main { grid-template-columns: 1fr; } }
        .panel { display: flex; flex-direction: column; gap: 18px; }

        .chat-wrap {
          background: #1a1a2e; border-radius: 16px;
          border: 1px solid rgba(255,255,255,0.07);
          overflow: hidden; flex: 1;
          display: flex; flex-direction: column; min-height: 220px;
        }
        .chat-title {
          padding: 12px 16px; font-size: 0.8rem; font-weight: 700; color: #888;
          background: rgba(255,255,255,0.04);
          border-bottom: 1px solid rgba(255,255,255,0.07); letter-spacing: 0.3px;
        }
        .chat-scroll {
          flex: 1; overflow-y: auto; padding: 14px;
          display: flex; flex-direction: column; gap: 10px; max-height: 240px;
        }
        .chat-empty { color: #555; font-size: 0.85rem; text-align: center; margin: auto; }

        .waiter-indicator {
          display: flex; align-items: center; gap: 12px;
          padding: 12px 20px; background: rgba(124,58,237,0.1);
          border-radius: 12px; margin: 10px 0;
          color: #7c3aed; font-weight: 600; font-size: 0.9rem;
          border: 1px solid rgba(124,58,237,0.2);
          animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        .pulse-mic {
          background: rgba(124,58,237,0.2);
          width: 44px; height: 44px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          position: relative;
        }
        .pulse-mic::after {
          content: ''; position: absolute;
          width: 100%; height: 100%; border-radius: 50%;
          background: #7c3aed; opacity: 0.4;
          animation: pulse-ring 1.5s cubic-bezier(0.24, 0, 0.38, 1) infinite;
        }
        @keyframes pulse-ring {
          0% { transform: scale(0.8); opacity: 0.5; }
          100% { transform: scale(2); opacity: 0; }
        }

        .mediator-action {
          padding: 12px;
          display: flex; justify-content: center;
          animation: bounceIn 0.5s ease;
        }
        @keyframes bounceIn {
          0% { transform: scale(0.9); opacity: 0; }
          70% { transform: scale(1.05); }
          100% { transform: scale(1); opacity: 1; }
        }
        .btn-waiter {
          background: linear-gradient(135deg, #4f46e5, #7c3aed);
          color: white; border: none;
          padding: 14px 32px; border-radius: 12px;
          font-weight: 800; font-size: 1rem;
          cursor: pointer; box-shadow: 0 8px 16px rgba(79,70,229,0.3);
          transition: all 0.2s;
        }
        .btn-waiter:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(79,70,229,0.4); }
        .btn-waiter:active { transform: scale(0.98); }

        .bubble { padding: 10px 14px; border-radius: 12px; max-width: 95%; }
        .bubble-user  { background: rgba(79,70,229,0.25); border: 1px solid rgba(79,70,229,0.3); align-self: flex-end; }
        .bubble-agent { background: rgba(124,58,237,0.2); border: 1px solid rgba(124,58,237,0.25); align-self: flex-start; }
        .bubble-provider { background: rgba(236,72,153,0.2); border: 1px solid rgba(236,72,153,0.25); align-self: flex-start; }
        .bubble-meta { display: flex; justify-content: space-between; margin-bottom: 4px; }
        .bubble-role { font-size: 0.7rem; font-weight: 700; color: #aaa; display: flex; align-items: center; gap: 6px; }
        .bubble-lang-tag {
          font-size: 0.6rem; background: rgba(255,255,255,0.1);
          padding: 1px 5px; border-radius: 4px; color: #888;
        }
        .bubble-time { font-size: 0.65rem; color: #555; }
        .bubble-text { font-size: 0.88rem; line-height: 1.5; color: #dde; }

        .avatar-wrap {
          background: #1a1a2e; border-radius: 16px;
          border: 1px solid rgba(255,255,255,0.07); overflow: hidden;
        }

        .success-card {
          background: linear-gradient(135deg, rgba(5,150,105,0.15), rgba(16,185,129,0.08));
          border: 1px solid rgba(16,185,129,0.35); border-radius: 16px;
          padding: 36px 24px; text-align: center;
          display: flex; flex-direction: column; align-items: center; gap: 12px;
        }
        .success-icon { font-size: 3rem; }
        .success-title { font-size: 1.4rem; font-weight: 800; color: #34d399; }
        .success-sub { color: #888; font-size: 0.9rem; }
        .btn-new {
          margin-top: 8px;
          background: linear-gradient(135deg, #059669, #047857);
          color: white; border: none;
          padding: 12px 28px; border-radius: 10px;
          font-weight: 700; cursor: pointer; font-size: 0.9rem;
          transition: all 0.2s; box-shadow: 0 4px 14px rgba(5,150,105,0.35);
        }
        .btn-new:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(5,150,105,0.5); }

        .fixed-mic-overlay {
          position: fixed;
          bottom: 40px;
          right: 40px;
          color: white;
          padding: 12px 24px;
          border-radius: 9999px;
          display: flex;
          align-items: center;
          gap: 12px;
          font-weight: 700;
          z-index: 1000;
          transition: all 0.3s ease;
        }
        
        .fixed-mic-overlay.pulsing {
          background: #ef4444;
          box-shadow: 0 10px 25px rgba(239, 68, 68, 0.4);
          animation: overlay-pulse 2s infinite;
        }
        
        .fixed-mic-overlay.paused {
          background: #64748b;
          box-shadow: 0 10px 25px rgba(100, 116, 139, 0.4);
        }
        
        @keyframes overlay-pulse {
          0% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.05); opacity: 0.9; }
          100% { transform: scale(1); opacity: 1; }
        }
        .mic-icon-pulse {
          animation: mic-bounce 1s infinite alternate;
        }
        .mic-icon-paused {
          opacity: 0.6;
        }
        @keyframes mic-bounce {
          from { transform: translateY(0); }
          to { transform: translateY(-2px); }
        }
        
        /* Placeholder Image Grid */
        .placeholder-grid-wrap {
          background: #1a1a2e;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 16px;
          padding: 20px;
          animation: fadeIn 0.3s ease;
        }
        
        .placeholder-title {
          font-size: 0.9rem;
          font-weight: 700;
          color: #7c3aed;
          margin-bottom: 16px;
          text-align: center;
          letter-spacing: 0.3px;
        }
        
        .placeholder-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
          gap: 16px;
        }
        
        .placeholder-card {
          background: rgba(124,58,237,0.08);
          border: 2px solid rgba(124,58,237,0.2);
          border-radius: 12px;
          overflow: hidden;
          cursor: pointer;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .placeholder-card:hover {
          transform: translateY(-4px);
          border-color: #7c3aed;
          box-shadow: 0 8px 20px rgba(124,58,237,0.3);
        }
        
        .placeholder-img {
          width: 100%;
          height: 120px;
          object-fit: cover;
          display: block;
        }
        
        .placeholder-label {
          padding: 10px 12px;
          text-align: center;
          font-size: 0.85rem;
          font-weight: 600;
          color: #ddd;
          text-transform: capitalize;
          background: rgba(0,0,0,0.3);
        }
      `}</style>
        </div>
    );
};

export default App;
