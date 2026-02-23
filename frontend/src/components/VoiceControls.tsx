import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Mic, MicOff, Send } from 'lucide-react';

interface VoiceControlsProps {
  onSendMessage: (text: string) => void;
  lang: string;
  waiterActive: boolean;
  agentSpeaking?: boolean;
  waiterLang?: string;
}

const VoiceControls: React.FC<VoiceControlsProps> = ({
  onSendMessage,
  waiterActive,
  agentSpeaking = false,
  waiterLang = 'hi',
}) => {
  const [isListening, setIsListening] = useState(false);
  const [inputText, setInputText] = useState('');
  const [liveTranscript, setLiveTranscript] = useState('');

  const recRef = useRef<any>(null);
  const shouldListenRef = useRef(false);
  const agentSpeakingRef = useRef(false);
  const onSendRef = useRef(onSendMessage);

  useEffect(() => { onSendRef.current = onSendMessage; }, [onSendMessage]);
  useEffect(() => { agentSpeakingRef.current = agentSpeaking; }, [agentSpeaking]);

  // Build SpeechRecognition once
  useEffect(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { console.warn('[STT] Not supported in this browser'); return; }

    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-IN';

    rec.onstart = () => { console.log('[STT] Started'); setIsListening(true); };

    rec.onend = () => {
      console.log('[STT] Ended, shouldListen:', shouldListenRef.current);
      setLiveTranscript('');
      if (shouldListenRef.current) {
        setTimeout(() => { try { rec.start(); } catch (_) {} }, 200);
      } else {
        setIsListening(false);
      }
    };

    rec.onerror = (e: any) => {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      console.error('[STT] Error:', e.error);
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        shouldListenRef.current = false;
        setIsListening(false);
      }
    };

    rec.onresult = (e: any) => {
      let interim = '';
      let finalText = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      if (interim) setLiveTranscript(interim);
      if (finalText.trim()) {
        setLiveTranscript('');
        console.log('[STT] ========================================');
        console.log('[STT] Final transcript received:', finalText.trim());
        console.log('[STT] Agent speaking?', agentSpeakingRef.current);
        if (!agentSpeakingRef.current) {
          console.log('[STT] ✓ SENDING to backend:', finalText.trim());
          onSendRef.current(finalText.trim());
        } else {
          console.log('[STT] ✗ IGNORED (agent speaking)');
        }
        console.log('[STT] ========================================');
      }
    };

    recRef.current = rec;
    return () => { shouldListenRef.current = false; try { rec.abort(); } catch (_) {} };
  }, []);

  // Update language when provider language is detected
  useEffect(() => {
    if (!recRef.current) return;
    const map: Record<string, string> = { hi: 'hi-IN', en: 'en-IN', ta: 'ta-IN', kn: 'kn-IN' };
    recRef.current.lang = map[waiterLang] || 'en-IN';
    console.log('[STT] Lang set to', recRef.current.lang);
  }, [waiterLang]);

  // Auto-start mic when provider mode activates
  useEffect(() => {
    if (waiterActive) { startListening(); } else { stopListening(); }
  }, [waiterActive]);

  const startListening = () => {
    if (!recRef.current || shouldListenRef.current) return;
    shouldListenRef.current = true;
    try { recRef.current.start(); console.log('[STT] start() called'); }
    catch (e) { console.warn('[STT] start() error:', e); }
  };

  const stopListening = () => {
    shouldListenRef.current = false;
    try { recRef.current?.stop(); } catch (_) {}
    setIsListening(false);
    setLiveTranscript('');
  };

  const handleToggleMic = useCallback(() => {
    isListening ? stopListening() : startListening();
  }, [isListening]);

  const handleSend = () => {
    const text = inputText.trim();
    if (text) { onSendRef.current(text); setInputText(''); }
  };

  return (
    <div className={`vc-wrap ${isListening ? 'listening' : ''} ${agentSpeaking ? 'agent-speaking' : ''}`}>
      <div className="vc-header">
        <div className="vc-title">
          <span>{agentSpeaking ? '🤖' : isListening ? '🎙️' : '📞'}</span>
          {agentSpeaking ? 'Agent speaking...' : isListening ? 'Listening to Provider...' : 'Provider / Voice Interface'}
        </div>
        <div
          className={`vc-mic-toggle ${isListening ? 'active' : ''} ${agentSpeaking ? 'paused' : ''}`}
          onClick={handleToggleMic}
        >
          {isListening ? <Mic size={24} /> : <MicOff size={24} />}
          <div className="vc-mic-ring" />
        </div>
      </div>

      {liveTranscript && (
        <div className="vc-interim">{liveTranscript}</div>
      )}

      <p className="vc-hint">
        {agentSpeaking
          ? 'Agent is speaking to the provider - mic paused.'
          : isListening
            ? 'Listening... speak naturally in any language.'
            : 'Tap the mic to start listening, or type below.'}
      </p>

      <div className="vc-row">
        <input
          className="vc-input"
          type="text"
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          placeholder='Type provider reply or "confirm"...'
          onKeyDown={e => e.key === 'Enter' && handleSend()}
        />
        <button className="vc-send" onClick={handleSend}><Send size={18} /></button>
      </div>

      <style>{`
        .vc-wrap {
          background: #1a1a2e;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 20px; padding: 20px;
          transition: all 0.3s ease; position: relative; overflow: hidden;
        }
        .vc-wrap.listening { border-color: #7c3aed; box-shadow: 0 0 30px rgba(124,58,237,0.15); }
        .vc-wrap.agent-speaking { border-color: #475569; }
        .vc-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .vc-title { display: flex; align-items: center; gap: 10px; font-size: 0.9rem; font-weight: 800; color: #fff; }
        .vc-mic-toggle {
          width: 52px; height: 52px; background: rgba(255,255,255,0.05);
          border-radius: 50%; display: flex; align-items: center; justify-content: center;
          cursor: pointer; transition: all 0.3s ease; position: relative;
          border: 2px solid rgba(255,255,255,0.1); color: #888;
        }
        .vc-mic-toggle.active { background: #7c3aed; color: #fff; border-color: transparent; box-shadow: 0 0 20px rgba(124,58,237,0.4); }
        .vc-mic-toggle.paused { background: #475569; color: #fff; border-color: transparent; }
        .vc-mic-toggle:hover { transform: scale(1.05); }
        .vc-mic-ring { position: absolute; width: 100%; height: 100%; border-radius: 50%; border: 2px solid #7c3aed; opacity: 0; pointer-events: none; }
        .active .vc-mic-ring { animation: mic-pulse 1.8s infinite; }
        @keyframes mic-pulse { 0% { transform: scale(1); opacity: 0.8; } 100% { transform: scale(1.7); opacity: 0; } }
        .vc-interim {
          background: rgba(124,58,237,0.1); border-left: 3px solid #7c3aed;
          padding: 8px 12px; border-radius: 8px; font-size: 0.85rem;
          color: #c4b5fd; margin-bottom: 12px; font-style: italic;
        }
        .vc-hint { font-size: 0.8rem; color: #94a3b8; margin-bottom: 18px; line-height: 1.4; }
        .vc-row { display: flex; gap: 12px; align-items: center; }
        .vc-input {
          flex: 1; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
          color: #eee; padding: 12px 16px; border-radius: 12px; font-size: 0.9rem; outline: none; transition: all 0.2s;
        }
        .vc-input:focus { border-color: #7c3aed; background: rgba(255,255,255,0.08); }
        .vc-send {
          background: #7c3aed; color: white; border: none;
          width: 44px; height: 44px; border-radius: 12px;
          display: flex; align-items: center; justify-content: center;
          cursor: pointer; transition: all 0.2s;
          box-shadow: 0 4px 12px rgba(124,58,237,0.3);
        }
        .vc-send:hover { background: #6d28d9; transform: translateY(-2px); }
        .vc-send:active { transform: scale(0.95); }
      `}</style>
    </div>
  );
};

export default VoiceControls;
