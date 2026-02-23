/**
 * Gemini Live Voice Component
 * Handles bidirectional audio streaming with Gemini Multimodal Live API
 * 16kHz PCM input, 24kHz PCM output with queue-based playback
 */

import { useEffect, useRef, useState } from 'react';

interface GeminiLiveVoiceProps {
  sessionId: string;
  onFoodImages?: (items: string[], summary: string) => void;
  onOrderConfirmed?: (summary: string) => void;
  onAgentSpeaking?: (speaking: boolean) => void;
}

interface AudioChunk {
  data: string; // base64
  sampleRate: number;
}

export default function GeminiLiveVoice({
  sessionId,
  onFoodImages,
  onOrderConfirmed,
  onAgentSpeaking
}: GeminiLiveVoiceProps) {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [transcript, setTranscript] = useState('');

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioWorkletRef = useRef<AudioWorkletNode | null>(null);
  
  // Audio playback queue
  const playbackQueueRef = useRef<AudioChunk[]>([]);
  const isPlayingRef = useRef(false);

  // Connect to WebSocket
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8080/ws/gemini-live/${sessionId}`);
    
    ws.onopen = () => {
      console.log('[GEMINI_LIVE] Connected to Gemini Live API');
      setIsConnected(true);
      
      // Start heartbeat
      const heartbeat = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
      
      (ws as any).heartbeat = heartbeat;
    };
    
    ws.onmessage = async (event) => {
      const message = JSON.parse(event.data);
      
      if (message.type === 'audio') {
        // Queue audio for playback
        playbackQueueRef.current.push({
          data: message.data,
          sampleRate: message.sampleRate || 24000
        });
        
        // Start playback if not already playing
        if (!isPlayingRef.current) {
          playAudioQueue();
        }
        
      } else if (message.type === 'text') {
        console.log('[GEMINI_LIVE] Text:', message.data);
        setTranscript(message.data);
        
      } else if (message.type === 'function_call') {
        const { function: funcName, food_items, user_summary, signal } = message;
        
        if (funcName === 'show_food_images' && onFoodImages) {
          onFoodImages(food_items, user_summary);
        } else if (funcName === 'order_confirmed' && onOrderConfirmed) {
          onOrderConfirmed(user_summary);
        }
      }
    };
    
    ws.onerror = (error) => {
      console.error('[GEMINI_LIVE] WebSocket error:', error);
    };
    
    ws.onclose = () => {
      console.log('[GEMINI_LIVE] Disconnected');
      setIsConnected(false);
      if ((ws as any).heartbeat) {
        clearInterval((ws as any).heartbeat);
      }
    };
    
    wsRef.current = ws;
    
    return () => {
      if ((ws as any).heartbeat) {
        clearInterval((ws as any).heartbeat);
      }
      ws.close();
    };
  }, [sessionId]);

  // Audio playback queue processor
  const playAudioQueue = async () => {
    if (isPlayingRef.current || playbackQueueRef.current.length === 0) {
      return;
    }
    
    isPlayingRef.current = true;
    setAgentSpeaking(true);
    onAgentSpeaking?.(true);
    
    while (playbackQueueRef.current.length > 0) {
      const chunk = playbackQueueRef.current.shift()!;
      await playAudioChunk(chunk);
    }
    
    isPlayingRef.current = false;
    setAgentSpeaking(false);
    onAgentSpeaking?.(false);
  };

  // Play single audio chunk
  const playAudioChunk = async (chunk: AudioChunk): Promise<void> => {
    return new Promise(async (resolve) => {
      try {
        if (!audioContextRef.current) {
          audioContextRef.current = new AudioContext({ sampleRate: chunk.sampleRate });
        }
        
        const audioContext = audioContextRef.current;
        
        // Decode base64 to ArrayBuffer
        const binaryString = atob(chunk.data);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }
        
        // Convert PCM bytes to Float32Array
        const int16Array = new Int16Array(bytes.buffer);
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
          float32Array[i] = int16Array[i] / 32768.0; // Convert to -1.0 to 1.0
        }
        
        // Create audio buffer
        const audioBuffer = audioContext.createBuffer(1, float32Array.length, chunk.sampleRate);
        audioBuffer.getChannelData(0).set(float32Array);
        
        // Play audio
        const source = audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContext.destination);
        source.onended = () => resolve();
        source.start();
        
      } catch (error) {
        console.error('[GEMINI_LIVE] Audio playback error:', error);
        resolve();
      }
    });
  };

  // Start/stop microphone
  const toggleListening = async () => {
    if (isListening) {
      stopListening();
    } else {
      await startListening();
    }
  };

  const startListening = async () => {
    try {
      console.log('[GEMINI_LIVE] Starting microphone...');
      
      // Get microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      });
      
      mediaStreamRef.current = stream;
      
      // Create AudioContext for processing
      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext({ sampleRate: 16000 });
      }
      
      const audioContext = audioContextRef.current;
      const source = audioContext.createMediaStreamSource(stream);
      
      // Use ScriptProcessorNode for audio capture (simple approach)
      // Use 3200 buffer at 16kHz ≈ 200ms chunks (smaller than previous 256ms)
      const processor = audioContext.createScriptProcessor(3200, 1, 1);
      
      processor.onaudioprocess = (e) => {
        if (!isListening || agentSpeaking) return; // Don't send while agent is speaking
        
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Convert Float32Array to Int16Array (PCM)
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        // Send to WebSocket
        const audioBase64 = btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
        
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: 'audio',
            data: audioBase64
          }));
        }
      };
      
      source.connect(processor);
      processor.connect(audioContext.destination);
      
      audioWorkletRef.current = processor as any;
      setIsListening(true);
      console.log('[GEMINI_LIVE] Microphone started');
      
    } catch (error) {
      console.error('[GEMINI_LIVE] Microphone error:', error);
      alert('Microphone access denied. Please allow microphone access.');
    }
  };

  const stopListening = () => {
    console.log('[GEMINI_LIVE] Stopping microphone...');
    
    if (audioWorkletRef.current) {
      audioWorkletRef.current.disconnect();
      audioWorkletRef.current = null;
    }
    
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    
    setIsListening(false);
  };

  // Send text message (for ISL interpretation)
  const sendText = (text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'text',
        data: text
      }));
      console.log('[GEMINI_LIVE] Sent text:', text);
    }
  };

  // Send user selection
  const sendUserSelection = (item: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'user_selection',
        item
      }));
      console.log('[GEMINI_LIVE] User selected:', item);
    }
  };

  // Send user confirmation
  const sendUserConfirmation = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'user_confirmation'
      }));
      console.log('[GEMINI_LIVE] User confirmed order');
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopListening();
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, []);

  // Expose methods via ref (for parent component)
  useEffect(() => {
    (window as any).geminiLiveVoice = {
      sendText,
      sendUserSelection,
      sendUserConfirmation,
      toggleListening,
      isConnected,
      isListening
    };
  }, [isConnected, isListening]);

  return (
    <div className="gemini-live-voice">
      {/* Status indicators */}
      <div style={{ padding: '10px', background: '#f0f0f0', borderRadius: '8px', marginBottom: '10px' }}>
        <div>
          <strong>Connection:</strong> {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
        </div>
        <div>
          <strong>Microphone:</strong> {isListening ? '🎤 Listening' : '🔇 Off'}
        </div>
        <div>
          <strong>Agent:</strong> {agentSpeaking ? '🔊 Speaking' : '🔇 Silent'}
        </div>
        {transcript && (
          <div style={{ marginTop: '8px', color: '#666', fontSize: '14px' }}>
            <strong>Transcript:</strong> {transcript}
          </div>
        )}
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: '10px' }}>
        <button 
          onClick={toggleListening}
          disabled={!isConnected}
          style={{
            padding: '12px 24px',
            fontSize: '16px',
            borderRadius: '8px',
            border: 'none',
            background: isListening ? '#ff4444' : '#4CAF50',
            color: 'white',
            cursor: isConnected ? 'pointer' : 'not-allowed',
            opacity: isConnected ? 1 : 0.5
          }}
        >
          {isListening ? '⏹️ Stop Listening' : '🎤 Start Listening'}
        </button>
      </div>
    </div>
  );
}
