import React, { useRef, useState, useCallback, useEffect } from 'react';
import Webcam from 'react-webcam';

interface WebcamCaptureProps {
  onUpload: (blob: Blob) => void;
  isProcessing: boolean;
}

const WebcamCapture: React.FC<WebcamCaptureProps> = ({ onUpload, isProcessing }) => {
  const webcamRef = useRef<Webcam>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [recordedChunks, setRecordedChunks] = useState<Blob[]>([]);
  const [hasRecording, setHasRecording] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleDataAvailable = useCallback(({ data }: BlobEvent) => {
    if (data.size > 0) {
      setRecordedChunks(prev => [...prev, data]);
    }
  }, []);

  const handleStopCaptureClick = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (countdownRef.current) clearInterval(countdownRef.current);
    setCapturing(false);
    setCountdown(0);
  }, []);

  const handleStartCaptureClick = useCallback(() => {
    setRecordedChunks([]);
    setHasRecording(false);
    setCapturing(true);
    setCountdown(8);

    if (webcamRef.current?.stream) {
      const recorder = new MediaRecorder(webcamRef.current.stream, { mimeType: 'video/webm' });
      recorder.addEventListener('dataavailable', handleDataAvailable);
      recorder.addEventListener('stop', () => setHasRecording(true));
      mediaRecorderRef.current = recorder;
      recorder.start();

      let secs = 8;
      countdownRef.current = setInterval(() => {
        secs -= 1;
        setCountdown(secs);
        if (secs <= 0) {
          clearInterval(countdownRef.current!);
        }
      }, 1000);

      setTimeout(() => handleStopCaptureClick(), 8000);
    }
  }, [handleDataAvailable, handleStopCaptureClick]);

  const handleProcess = useCallback(() => {
    if (recordedChunks.length === 0) return;
    const blob = new Blob(recordedChunks, { type: 'video/webm' });
    onUpload(blob);
    setRecordedChunks([]);
    setHasRecording(false);
  }, [recordedChunks, onUpload]);

  const handleDiscard = useCallback(() => {
    setRecordedChunks([]);
    setHasRecording(false);
  }, []);

  return (
    <div className="webcam-card">
      <div className="webcam-header">
        <span className="webcam-title">📹 ISL Camera</span>
        {capturing && (
          <span className="rec-badge">
            <span className="rec-dot" /> REC {countdown}s
          </span>
        )}
      </div>

      <div className="webcam-preview">
        <Webcam audio={false} ref={webcamRef} muted={true} className="webcam-video" />
        {isProcessing && (
          <div className="processing-overlay">
            <div className="spinner" />
            <span>Analyzing sign language…</span>
          </div>
        )}
      </div>

      <div className="webcam-controls">
        {!capturing && !hasRecording && !isProcessing && (
          <button className="btn btn-primary" onClick={handleStartCaptureClick}>
            ✋ Sign Now
          </button>
        )}
        {capturing && (
          <button className="btn btn-danger" onClick={handleStopCaptureClick}>
            ⏹ Stop Recording
          </button>
        )}
        {hasRecording && !isProcessing && (
          <>
            <button className="btn btn-success" onClick={handleProcess}>
              ⚡ Process Video
            </button>
            <button className="btn btn-ghost" onClick={handleDiscard}>
              🗑 Discard
            </button>
          </>
        )}
        {isProcessing && (
          <button className="btn btn-disabled" disabled>
            ⏳ Processing…
          </button>
        )}
      </div>

      <style>{`
        .webcam-card {
          background: #1a1a2e;
          border-radius: 16px;
          overflow: hidden;
          border: 1px solid rgba(255,255,255,0.08);
          box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .webcam-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 18px;
          background: rgba(255,255,255,0.05);
          border-bottom: 1px solid rgba(255,255,255,0.07);
          font-size: 0.9rem;
          font-weight: 600;
          color: #ccc;
        }
        .rec-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          color: #ff4d4d;
          font-size: 0.82rem;
          font-weight: 700;
          letter-spacing: 0.5px;
        }
        .rec-dot {
          width: 8px; height: 8px;
          background: #ff4d4d;
          border-radius: 50%;
          animation: blink 1s infinite;
        }
        @keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0; } }
        .webcam-preview {
          position: relative;
          width: 100%;
          aspect-ratio: 4/3;
          background: #000;
        }
        .webcam-video {
          width: 100%;
          height: 100%;
          object-fit: cover;
          display: block;
        }
        .processing-overlay {
          position: absolute;
          inset: 0;
          background: rgba(0,0,0,0.7);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
          color: #fff;
          font-size: 0.95rem;
          font-weight: 600;
        }
        .spinner {
          width: 40px; height: 40px;
          border: 4px solid rgba(255,255,255,0.2);
          border-top-color: #7c3aed;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .webcam-controls {
          display: flex;
          gap: 10px;
          padding: 14px 18px;
          flex-wrap: wrap;
        }
        .btn {
          flex: 1;
          padding: 10px 18px;
          border: none;
          border-radius: 10px;
          font-size: 0.875rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
        }
        .btn:active { transform: scale(0.96); }
        .btn-primary {
          background: linear-gradient(135deg, #7c3aed, #4f46e5);
          color: white;
          box-shadow: 0 4px 12px rgba(124,58,237,0.4);
        }
        .btn-primary:hover { box-shadow: 0 6px 20px rgba(124,58,237,0.6); }
        .btn-danger {
          background: linear-gradient(135deg, #dc2626, #b91c1c);
          color: white;
          animation: pulse-btn 1.5s infinite;
        }
        @keyframes pulse-btn { 0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,0.4)} 50%{box-shadow:0 0 0 8px rgba(220,38,38,0)} }
        .btn-success {
          background: linear-gradient(135deg, #059669, #047857);
          color: white;
          box-shadow: 0 4px 12px rgba(5,150,105,0.4);
        }
        .btn-success:hover { box-shadow: 0 6px 20px rgba(5,150,105,0.6); }
        .btn-ghost {
          background: rgba(255,255,255,0.08);
          color: #aaa;
          border: 1px solid rgba(255,255,255,0.1);
        }
        .btn-ghost:hover { background: rgba(255,255,255,0.14); }
        .btn-disabled {
          background: rgba(255,255,255,0.05);
          color: #666;
          cursor: not-allowed;
        }
      `}</style>
    </div>
  );
};

export default WebcamCapture;
