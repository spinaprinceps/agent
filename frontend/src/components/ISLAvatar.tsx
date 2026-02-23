import React, { Suspense, useState, useEffect, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, useGLTF, useAnimations } from '@react-three/drei';

const ClipPlayer = ({ clipName }: { clipName: string }) => {
    // In a real app, this would dynamically load models/clipName.gltf
    // For MVP, we'll try to load or show a placeholder if clip not found.
    const modelUrl = `/models/${clipName}.gltf`;

    // Custom hook to try load, with fallback logic
    const { scene, animations } = useGLTF(modelUrl);
    const { actions, names } = useAnimations(animations, scene);

    useEffect(() => {
        if (names.length > 0) {
            actions[names[0]]?.reset().fadeIn(0.5).play();
        }
    }, [names, actions]);

    return <primitive object={scene} scale={2} position={[0, -2, 0]} />;
};

const PlaceholderAvatar = () => {
    return (
        <mesh position={[0, 0, 0]}>
            <sphereGeometry args={[1, 32, 32]} />
            <meshStandardMaterial color="orange" />
        </mesh>
    );
};

interface ISLAvatarProps {
    responseSequence: string[]; // List of words/phrases to sign
}

const ISLAvatar: React.FC<ISLAvatarProps> = ({ responseSequence }) => {
    const [currentClipIndex, setCurrentClipIndex] = useState(-1);

    useEffect(() => {
        if (responseSequence.length > 0) {
            setCurrentClipIndex(0);
        }
    }, [responseSequence]);

    useEffect(() => {
        if (currentClipIndex >= 0 && currentClipIndex < responseSequence.length) {
            const timer = setTimeout(() => {
                setCurrentClipIndex(prev => prev + 1);
            }, 3000); // 3 seconds per sign clip
            return () => clearTimeout(timer);
        } else {
            setCurrentClipIndex(-1);
        }
    }, [currentClipIndex, responseSequence]);

    return (
        <div className="canvas-container" style={{ height: '400px', width: '100%', background: '#111', borderRadius: '8px' }}>
            <Canvas camera={{ position: [0, 0, 5], fov: 50 }}>
                <ambientLight intensity={0.5} />
                <pointLight position={[10, 10, 10]} />
                <Suspense fallback={<PlaceholderAvatar />}>
                    {currentClipIndex >= 0 ? (
                        <ClipPlayer clipName={responseSequence[currentClipIndex]} />
                    ) : (
                        <mesh position={[0, -1, 0]}>
                            <boxGeometry args={[1, 3, 1]} />
                            <meshStandardMaterial color="#444" />
                        </mesh>
                    )}
                </Suspense>
                <OrbitControls />
            </Canvas>
            <div className="sign-label">
                {currentClipIndex >= 0 ? `Signing: ${responseSequence[currentClipIndex]}` : 'Waiting for input...'}
            </div>
            <style>{`
        .canvas-container { position: relative; }
        .sign-label { 
            position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%);
            background: rgba(0,0,0,0.7); color: white; padding: 4px 12px; border-radius: 20px;
        }
      `}</style>
        </div>
    );
};

export default ISLAvatar;
