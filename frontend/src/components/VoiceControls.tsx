import React, { useState, useEffect, useRef } from 'react';
import { Mic, MicOff, Send } from 'lucide-react';

interface VoiceControlsProps {
  onSendMessage: (text: string) => void;
  lang: string;
  waiterActive: boolean;
}

const VoiceControls: React.FC<VoiceControlsProps> = ({ onSendMessage, lang, waiterActive }) => {
  const [inputText, setInputText] = useState('');
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRecognition) {
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = true;
      recognitionRef.current.interimResults = false;
      recognitionRef.current.lang = lang === 'hi' ? 'hi-IN' : 'en-IN';

      recognitionRef.current.onresult = (event: any) => {
        const transcript = event.results[event.results.length - 1][0].transcript;
        console.log('[STT] Result:', transcript);
        onSendMessage(transcript);
      };

      recognitionRef.current.onend = () => {
        if (waiterActive && isListening) {
          try { recognitionRef.current.start(); } catch (e) { }
        } else {
          setIsListening(false);
        }
      };
    }
    return () => recognitionRef.current?.stop();
  }, [onSendMessage, lang, waiterActive, isListening]);

  useEffect(() => {
    if (waiterActive && recognitionRef.current && !isListening) {
      handleToggleMic();
    } else if (!waiterActive && isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
    }
  }, [waiterActive]);

  const handleToggleMic = () => {
    if (!recognitionRef.current) return;
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      try {
        recognitionRef.current.start();
        setIsListening(true);
      } catch (e) {
        console.error('[STT] Start error:', e);
      }
    }
  };

  const handleSend = () => {
    if (inputText.trim()) {
      onSendMessage(inputText.trim());
      setInputText('');
    }
  };

  return (
    <div className={`vc-wrap ${isListening ? 'listening' : ''}`}>
      <div className="vc-header">
        <div className="vc-title">
          <span>{isListening ? '🎙️' : '📞'}</span>
          {isListening ? 'Listening to Provider...' : 'Provider / Voice Interface'}
        </div>
        <div className={`vc-mic-toggle ${isListening ? 'active' : ''}`} onClick={handleToggleMic}>
          {isListening ? <Mic size={24} /> : <MicOff size={24} />}
          <div className="vc-mic-ring"></div>
        </div>
      </div>

      <p className="vc-hint">
        {isListening ? 'Speak naturally. Tap the mic to pause.' : 'Tap the microphone to start listening or type a reply.'}
      </p>

      <div className="vc-row">
        <input
          className="vc-input"
          type="text"
          value={inputText}
          onChange={e => setInputText(e.target.value)}
          placeholder='Type reply or "yes" to confirm…'
          onKeyDown={e => e.key === 'Enter' && handleSend()}
        />
        <button className="vc-send" onClick={handleSend}>
          <Send size={18} />
        </button>
      </div>

      <style>{`
        .vc-wrap {
          background: #1a1a2e;
          border: 1px solid rgba(255,255,255,0.07);
          border-radius: 20px;
          padding: 20px;
          transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
          position: relative;
          overflow: hidden;
        }
        .vc-wrap.listening {
          border-color: #7c3aed;
          box-shadow: 0 0 30px rgba(124,58,237,0.15);
        }
        .vc-header {
           display: flex; justify-content: space-between; align-items: center;
           margin-bottom: 12px;
        }
        .vc-title {
          display: flex; align-items: center; gap: 10px;
          font-size: 0.9rem; font-weight: 800; color: #fff;
          letter-spacing: 0.3px;
        }
        .vc-mic-toggle {
          width: 52px; height: 52px;
          background: rgba(255,255,255,0.05);
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          cursor: pointer;
          transition: all 0.3s ease;
          position: relative;
          border: 2px solid rgba(255,255,255,0.1);
          color: #888;
        }
        .vc-mic-toggle.active {
          background: #7c3aed;
          color: #fff;
          border-color: transparent;
          box-shadow: 0 0 20px rgba(124,58,237,0.4);
        }
        .vc-mic-toggle:hover {
          transform: scale(1.05);
          background: rgba(124, 58, 237, 0.2);
        }
        .vc-mic-toggle.active:hover {
          background: #6d28d9;
        }
        
        .vc-mic-ring {
          position: absolute;
          width: 100%; height: 100%;
          border-radius: 50%;
          border: 2px solid #7c3aed;
          opacity: 0;
          pointer-events: none;
        }
        .active .vc-mic-ring {
          animation: mic-pulse 2s infinite;
        }
        @keyframes mic-pulse {
          0% { transform: scale(1); opacity: 0.8; }
          100% { transform: scale(1.6); opacity: 0; }
        }

        .vc-hint {
          font-size: 0.8rem; color: #94a3b8; margin-bottom: 18px;
          line-height: 1.4;
        }
        .vc-row { display: flex; gap: 12px; align-items: center; }
        .vc-input {
          flex: 1;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.1);
          color: #eee;
          padding: 12px 16px;
          border-radius: 12px;
          font-size: 0.9rem;
          outline: none;
          transition: all 0.2s;
        }
        .vc-input:focus { 
          border-color: #7c3aed;
          background: rgba(255,255,255,0.08);
        }
        .vc-send {
          background: #7c3aed;
          color: white; border: none;
          width: 44px; height: 44px;
          border-radius: 12px;
          display: flex; align-items: center; justify-content: center;
          cursor: pointer;
          transition: all 0.2s;
          box-shadow: 0 4px 12px rgba(124,58,237,0.3);
        }
        .vc-send:hover { 
          background: #6d28d9;
          transform: translateY(-2px);
          box-shadow: 0 6px 16px rgba(124,58,237,0.4);
        }
        .vc-send:active { transform: scale(0.95); }
      `}</style>
    </div>
  );
};

export default VoiceControls;
