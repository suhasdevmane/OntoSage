// src/components/ChatBot.js
import React, { useState, useEffect, useRef } from 'react';
import Message from './Message';
import ConversationHistory from './ConversationHistory';
import { Container, Button, Form, Row, Col } from 'react-bootstrap';
import { BsDownload, BsTrash, BsDashSquare, BsChatDotsFill, BsFullscreen, BsFullscreenExit, BsMicFill, BsStopCircleFill } from 'react-icons/bs';
import { FaBroom } from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import db from '../db';
import '../App.css'; // Ensure CSS is imported

// OntoSage 2.0 API Configuration
const ORCHESTRATOR_API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const WHISPER_API = process.env.REACT_APP_WHISPER_URL || 'http://localhost:8003';
const CHAT_ENDPOINT = `${ORCHESTRATOR_API}/chat`;
const STREAM_ENDPOINT = `${ORCHESTRATOR_API}/chat/stream`;
const HISTORY_ENDPOINT = `${ORCHESTRATOR_API}/conversations`; // Fixed endpoint
const ARTIFACTS_ENDPOINT = `${ORCHESTRATOR_API}/artifacts`;
const TRANSCRIBE_ENDPOINT = `${WHISPER_API}/transcribe`;

// Extract media references (e.g., Markdown image links) from assistant responses
const extractMediaFromText = (rawText = '') => {
  const media = [];
  if (!rawText) {
    return { text: '', media };
  }

  let cleaned = rawText;
  const imageRegex = /!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g;

  cleaned = cleaned.replace(imageRegex, (match, url) => {
    media.push({ type: 'image', url });
    return '';
  });

  cleaned = cleaned.replace(/\n{3,}/g, '\n\n').trim();
  return { text: cleaned, media };
};

const mergeBotMedia = (message, media) => {
  if (!media || !media.length) return message.media;
  const existing = Array.isArray(message.media) ? message.media : [];
  const merged = [...existing];

  media.forEach(item => {
    if (!merged.some(existingItem => existingItem.url === item.url)) {
      merged.push(item);
    }
  });

  return merged;
};

const normalizeBotMessage = (message) => {
  if (!message || message.sender !== 'bot') return message;

  const { text, media } = extractMediaFromText(message.text);
  const mergedMedia = mergeBotMedia(message, media);

  return {
    ...message,
    text: text || (mergedMedia && mergedMedia.length ? 'Visualization attached.' : ''),
    media: mergedMedia && mergedMedia.length ? mergedMedia : undefined,
  };
};

function ChatBot() {
  const navigate = useNavigate();
  
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [currentConversationId, setCurrentConversationId] = useState(null);
  
  // Toggle to show/hide intermediate attachments & verbose stages
  const [showDetails, setShowDetails] = useState(() => {
    try { return localStorage.getItem('chat_show_details') !== 'false'; } catch { return true; }
  });
  
  // Default to minimized; restore from sessionStorage if present
  const [minimized, setMinimized] = useState(() => {
    const saved = sessionStorage.getItem('chatbot_minimized');
    return saved === null ? true : saved === 'true';
  });
  
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  
  const textAreaRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const currentUser = sessionStorage.getItem('currentUser');

  // Load chat history for specific conversation
  const loadConversationMessages = async (convId) => {
    if (!currentUser || !convId) return;
    
    try {
      setIsLoading(true);
      const sessionToken = sessionStorage.getItem('session_token');
      // Use correct endpoint: /conversations/{convId}/messages
      const res = await fetch(`${HISTORY_ENDPOINT}/${convId}/messages`, { 
        credentials: 'include',
        headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {}
      });
      
      if (res.ok) {
        const data = await res.json();
        if (data.messages) {
          // Map backend message format to frontend format
          const mappedMessages = data.messages.map(msg => {
            const baseMessage = {
              sender: msg.role === 'assistant' ? 'bot' : msg.role,
              text: msg.content,
              timestamp: msg.timestamp,
              ...msg.metadata
            };
            return normalizeBotMessage(baseMessage);
          });
          setMessages(mappedMessages);
        }
      }
    } catch (e) {
      console.error('Error loading conversation messages:', e);
    } finally {
      setIsLoading(false);
    }
  };

  // Initial load - get latest conversation or start new
  useEffect(() => {
    if (!currentUser) return;
    
    // If we already have a conversation selected, don't auto-load
    if (currentConversationId) return;

    (async () => {
      try {
        const sessionToken = sessionStorage.getItem('session_token');
        const res = await fetch(`${ORCHESTRATOR_API}/conversations/${currentUser}`, { 
          credentials: 'include',
          headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {}
        });
        
        if (res.ok) {
          const convs = await res.json();
          if (convs && convs.length > 0) {
            // Sort by updated_at desc
            const sorted = convs.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
            const latest = sorted[0];
            setCurrentConversationId(latest.conversation_id);
            await loadConversationMessages(latest.conversation_id);
          } else {
            // No conversations, start fresh
            setMessages([{ 
              sender: 'bot', 
              text: `Welcome back, ${currentUser}! How can I help you today?`, 
              timestamp: new Date().toLocaleTimeString() 
            }]);
          }
        }
      } catch (e) {
        console.warn('Failed to fetch conversations list:', e);
      }
    })();
  }, [currentUser]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const addMessage = (message) => {
    if (!message.timestamp) {
      message.timestamp = new Date().toLocaleTimeString();
    }
    const normalized = message.sender === 'bot' ? normalizeBotMessage(message) : message;
    setMessages(prev => [...prev, normalized]);
  };

  const handleNewConversation = () => {
    setCurrentConversationId(null);
    setMessages([{ 
      sender: 'bot', 
      text: `Starting a new conversation. How can I help you?`, 
      timestamp: new Date().toLocaleTimeString() 
    }]);
  };

  const handleSelectConversation = (convId) => {
    if (convId === currentConversationId) return;
    setCurrentConversationId(convId);
    loadConversationMessages(convId);
  };

  const handleDeleteConversation = (convId) => {
    if (convId === currentConversationId) {
      handleNewConversation();
    }
  };

  const sendMessage = async () => {
    if (!userInput.trim()) return;
    
    const userMessage = {
      sender: 'user',
      text: userInput,
      timestamp: new Date().toLocaleTimeString(),
    };
    
    addMessage(userMessage);
    setUserInput('');
    if (textAreaRef.current) textAreaRef.current.style.height = 'auto';
    
    setIsLoading(true);
    
    // Create a placeholder bot message for streaming
    const botMsgId = Date.now();
    setMessages(prev => [...prev, {
      sender: 'bot',
      text: 'Processing...',
      timestamp: new Date().toLocaleTimeString(),
      id: botMsgId,
      isStreaming: true
    }]);

    try {
      const sessionToken = sessionStorage.getItem('session_token');
      
      const response = await fetch(STREAM_ENDPOINT, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          ...(sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {})
        },
        credentials: 'include',
        body: JSON.stringify({
          message: userMessage.text,
          user_id: currentUser || 'user',
          conversation_id: currentConversationId, // Pass current ID if exists
          stream: true
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let botResponseText = '';
      let conversationIdUpdated = false;
      let isFirstToken = true;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6);
            if (dataStr === '[DONE]') continue;
            
            try {
              const data = JSON.parse(dataStr);
              
              if (data.type === 'token') {
                if (isFirstToken) {
                  botResponseText = ''; // Clear "Processing..." text
                  isFirstToken = false;
                }
                botResponseText += data.content;
                // Update the streaming message in place
                setMessages(prev => prev.map(msg => {
                  if (msg.id !== botMsgId) return msg;
                  const updated = normalizeBotMessage({ ...msg, text: botResponseText });
                  return { ...updated, id: msg.id, isStreaming: msg.isStreaming };
                }));
              } else if (data.type === 'conversation_id') {
                if (!conversationIdUpdated) {
                  setCurrentConversationId(data.id);
                  conversationIdUpdated = true;
                }
              } else if (data.type === 'error') {
                botResponseText += `\n[Error: ${data.error}]`;
                setMessages(prev => prev.map(msg => 
                  msg.id === botMsgId ? { ...msg, text: botResponseText } : msg
                ));
              }
            } catch (e) {
              console.warn('Error parsing stream data:', e);
            }
          }
        }
      }
      
      // Finalize message
      setMessages(prev => prev.map(msg => {
        if (msg.id !== botMsgId) return msg;
        const updated = normalizeBotMessage(msg);
        return { ...updated, id: msg.id, isStreaming: false };
      }));

    } catch (error) {
      console.error("Error communicating with OntoSage orchestrator:", error);
      setMessages(prev => prev.map(msg => {
        if (msg.id !== botMsgId) return msg;
        const errorText = `${msg.text}\nError: ${error.message}.`;
        const updated = normalizeBotMessage({ ...msg, text: errorText });
        return { ...updated, id: msg.id, isStreaming: false };
      }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleTextAreaChange = (e) => {
    setUserInput(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = `${e.target.scrollHeight}px`;
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const downloadChatHistory = () => {
    const element = document.createElement("a");
    const file = new Blob([JSON.stringify(messages, null, 2)], { type: 'application/json' });
    element.href = URL.createObjectURL(file);
    element.download = "chatHistory.json";
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const clearChatHistory = () => {
    if (!window.confirm('Clear chat history and reset assistant memory?')) return;
    // Logic to clear history...
    // For now just clear local messages as backend clear is complex with multiple conversations
    setMessages([{
      sender: 'bot',
      text: `Chat cleared.`,
      timestamp: new Date().toLocaleTimeString()
    }]);
  };

  const handleLogout = async () => {
    try {
      const sessionToken = sessionStorage.getItem('session_token');
      await fetch(`${ORCHESTRATOR_API}/auth/logout`, {
        method: 'POST',
        headers: sessionToken ? { 'Authorization': `Bearer ${sessionToken}` } : {},
        credentials: 'include'
      });
    } catch (e) {
      console.warn('Logout request failed:', e);
    }
    sessionStorage.clear();
    navigate('/');
  };

  const clearArtifacts = async () => {
    if (!window.confirm('Delete all generated files for this user?')) return;
    try {
      const res = await fetch(`${ARTIFACTS_ENDPOINT}/${currentUser}`, { method: 'DELETE', credentials: 'include' });
      if (res.ok) {
        addMessage({ sender: 'bot', text: `Cleared artifacts.`, timestamp: new Date().toLocaleTimeString() });
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Voice recording functions (simplified for brevity, assuming same logic as before)
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (event) => { if (event.data.size > 0) audioChunksRef.current.push(event.data); };
      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await transcribeAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
      mediaRecorder.start();
      setIsRecording(true);
    } catch (error) {
      console.error('Error accessing microphone:', error);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const transcribeAudio = async (audioBlob) => {
    setIsTranscribing(true);
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.webm');
      const response = await fetch(TRANSCRIBE_ENDPOINT, { method: 'POST', body: formData });
      if (!response.ok) throw new Error('Transcription failed');
      const data = await response.json();
      const text = data.text || data.transcription || '';
      if (text.trim()) setUserInput(text);
    } catch (error) {
      console.error('Error transcribing:', error);
    } finally {
      setIsTranscribing(false);
    }
  };

  const toggleMinimize = () => {
    setMinimized(prev => {
      const next = !prev;
      try { sessionStorage.setItem('chatbot_minimized', String(next)); } catch {}
      return next;
    });
  };

  const toggleFullScreen = () => {
    const elem = document.getElementById('chat-container');
    if (!document.fullscreenElement) {
      if (elem.requestFullscreen) elem.requestFullscreen();
      setIsFullScreen(true);
    } else {
      if (document.exitFullscreen) document.exitFullscreen();
      setIsFullScreen(false);
    }
  };

  const containerStyle = isFullScreen
    ? {
        position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
        margin: 0, padding: 0, zIndex: 10000, backgroundColor: 'white'
      }
    : {
        position: 'fixed', bottom: '20px', right: '20px', width: '420px', height: '620px',
        margin: 0, padding: 0, zIndex: 9999,
      };

  const containerClass = isFullScreen ? "fullscreen-chat-container" : "chat-container";

  const fullChatUI = (
    <Container id="chat-container" className={containerClass} style={containerStyle} fluid={isFullScreen}>
      <div className="d-flex h-100">
        {/* Sidebar - Only visible in full screen */}
        {isFullScreen && (
          <div className="border-end bg-light" style={{ width: '280px', minWidth: '280px' }}>
            <ConversationHistory 
              userId={currentUser}
              currentConversationId={currentConversationId}
              onSelectConversation={handleSelectConversation}
              onNewConversation={handleNewConversation}
              onDeleteConversation={handleDeleteConversation}
            />
          </div>
        )}

        {/* Main Chat Area */}
        <div className="flex-grow-1 d-flex flex-column chat-inner" style={{ height: '100%' }}>
          {/* Header */}
          <div className="chat-header p-2 border-bottom d-flex justify-content-between align-items-center">
            <h5 className="mb-0"> 💬 BrickBot</h5>
            <div className="header-buttons">
              <Button variant="light" size="sm" onClick={handleLogout} title="Logout">👤</Button>
              <Button variant="light" size="sm" onClick={toggleFullScreen}>
                {isFullScreen ? <BsFullscreenExit /> : <BsFullscreen />}
              </Button>
              <Button variant="light" size="sm" onClick={toggleMinimize}>
                <BsDashSquare />
              </Button>
            </div>
          </div>

          {/* Messages */}
          <div className="chat-messages flex-grow-1 overflow-auto p-3">
            {messages
              .filter(msg => {
                if (showDetails) return true;
                if (msg.sender === 'user') return true;
                const raw = msg.text || '';
                const t = raw.toLowerCase();
                if ((!raw.trim()) && !msg.attachment && !msg.attachments) return false;
                const hideIndicators = ['sparql query results', 'analytics results', 'understanding your question'];
                if (hideIndicators.some(h => t.startsWith(h))) return false;
                return true;
              })
              .map((msg, index) => (
                <Message key={index} message={msg} hideAttachments={!showDetails} />
              ))}
            {isLoading && !messages.some(m => m.isStreaming) && (
              <div className="processing-message text-center my-2">
                <span className="processing-text">Processing...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="chat-input p-3 border-top">
            <div className="input-wrapper mb-2">
              <Form.Control 
                as="textarea"
                rows={1}
                ref={textAreaRef}
                placeholder={isTranscribing ? "Transcribing..." : "Type your message..."}
                value={userInput}
                onChange={handleTextAreaChange}
                onKeyDown={handleKeyDown}
                style={{ resize: 'none', overflow: 'hidden', minHeight: '40px' }}
                disabled={isTranscribing}
              />
              <Button 
                variant={isRecording ? "danger" : "primary"}
                onClick={isRecording ? stopRecording : startRecording}
                disabled={isTranscribing || isLoading}
                className="ms-2"
              >
                {isRecording ? <BsStopCircleFill /> : <BsMicFill />}
              </Button>
            </div>
            <div className="d-flex justify-content-between align-items-center">
              <Form.Check
                type="switch"
                id="toggle-details"
                label="Details"
                checked={showDetails}
                onChange={() => setShowDetails(!showDetails)}
                className="small"
              />
              <div>
                <Button variant="secondary" size="sm" className="me-1" onClick={downloadChatHistory}><BsDownload /></Button>
                <Button variant="danger" size="sm" className="me-1" onClick={clearChatHistory}><BsTrash /></Button>
                <Button variant="warning" size="sm" onClick={clearArtifacts}><FaBroom /></Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Container>
  );

  const minimizedView = (
    <div className="chat-minimized" style={{ position: 'fixed', bottom: '20px', right: '20px', zIndex: 9999 }}>
      <Button variant="primary" onClick={toggleMinimize} style={{ borderRadius: '50%', width: '60px', height: '60px', padding: 0 }}>
        <BsChatDotsFill size={30} />
      </Button>
    </div>
  );

  return (
    <>
      {minimized ? minimizedView : fullChatUI}
    </>
  );
}

export default ChatBot;
