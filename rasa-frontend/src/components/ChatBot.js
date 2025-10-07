// src/components/ChatBot.js
import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import Message from './Message';
import { Container, Button, Form } from 'react-bootstrap';
import { BsDownload, BsTrash, BsDashSquare, BsChatDotsFill, BsFullscreen, BsFullscreenExit } from 'react-icons/bs';
import { FaBroom } from 'react-icons/fa';
import db from '../db';
import '../App.css'; // Ensure CSS is imported

const API_BASE = 'http://localhost:8080/api';

const RASA_ENDPOINT = "http://localhost:5005/webhooks/rest/webhook";

function ChatBot() {
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  // Toggle to show/hide intermediate attachments & verbose stages
  // Persisted in localStorage under 'chat_show_details'. When off:
  //  - Filters out stage/result messages (SPARQL, SQL, analytics payload/results)
  //  - Suppresses attachments in Message component (hideAttachments prop)
  //  - Keeps user messages, final summary, greetings, errors.
  const [showDetails, setShowDetails] = useState(() => {
    try { return localStorage.getItem('chat_show_details') !== 'false'; } catch { return true; }
  });
  // Default to minimized; restore from sessionStorage if present
  const [minimized, setMinimized] = useState(() => {
    const saved = sessionStorage.getItem('chatbot_minimized');
    return saved === null ? true : saved === 'true';
  });
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [isLoading, setIsLoading] = useState(false); // New loading state
  const textAreaRef = useRef(null);
  const messagesEndRef = useRef(null);
  const currentUser = sessionStorage.getItem('currentUser');


  // Load chat history from server on mount, fallback to Dexie
  useEffect(() => {
    if (!currentUser) return;
    (async () => {
      try {
  const res = await fetch(`${API_BASE}/get_history`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          const msgs = Array.isArray(data.messages) ? data.messages : [];
          if (msgs.length > 0) {
            setMessages(msgs);
            await db.chatHistory.where('username').equals(currentUser).modify({ messages: msgs });
            return;
          }
        }
      } catch (e) {
        console.warn('Falling back to Dexie for chat history:', e);
      }
      // Dexie fallback or default greeting
      const record = await db.chatHistory.where('username').equals(currentUser).first();
      if (record && record.messages && record.messages.length > 0) {
        setMessages(record.messages);
      } else {
        const greet = [{ sender: 'bot', text: 'Welcome to our chat! How can I help you today?', timestamp: new Date().toLocaleTimeString() }];
        setMessages(greet);
        await db.chatHistory.add({ username: currentUser, messages: greet });
      }
    })();
  }, [currentUser]);

  // Save chat history locally and to server; auto-scroll
  useEffect(() => {
    if (!currentUser) return;
    (async () => {
      const record = await db.chatHistory.where('username').equals(currentUser).first();
      if (record) {
        await db.chatHistory.update(record.id, { messages });
      } else {
        await db.chatHistory.add({ username: currentUser, messages });
      }
      try {
        await fetch(`${API_BASE}/save_history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ messages })
        });
      } catch (e) {
        console.warn('Failed to sync history to server:', e);
      }
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    })();
  }, [messages, currentUser]);

  const addMessage = (message) => {
    if (!message.timestamp) {
      message.timestamp = new Date().toLocaleTimeString();
    }
    setMessages(prev => [...prev, message]);
  };

  const sendMessage = async () => {
    if (!userInput.trim()) return;
    const userMessage = {
      sender: 'user',
      text: userInput,
      timestamp: new Date().toLocaleTimeString(),
    };
    addMessage(userMessage);
    setIsLoading(true); // Set loading state to true
    try {
  const response = await axios.post(RASA_ENDPOINT, {
    sender: currentUser || 'user',
    message: userInput,
    metadata: { show_details: showDetails }
  });
      const botMessages = response.data.map(msg => ({
        sender: 'bot',
        ...msg,
        timestamp: new Date().toLocaleTimeString(),
      }));
      botMessages.forEach(msg => addMessage(msg));
    } catch (error) {
      console.error("Error communicating with Rasa:", error);
      addMessage({
        sender: 'bot',
        text: "Error communicating with the server.",
        timestamp: new Date().toLocaleTimeString(),
      });
    } finally {
      setIsLoading(false); // Clear loading state
    }
    setUserInput('');
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
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
    (async () => {
      try {
        if (currentUser) {
          const rec = await db.chatHistory.where('username').equals(currentUser).first();
          if (rec) await db.chatHistory.update(rec.id, { messages: [] });
        }
      } catch {}
      try {
        // Reset Rasa tracker memory for this user
        if (currentUser) {
          await axios.post(`http://localhost:5005/conversations/${encodeURIComponent(currentUser)}/events`, [
            { event: 'restart' }
          ]);
        }
      } catch (e) {
        console.warn('Failed to reset Rasa conversation:', e);
      }
      // Finally, clear UI state (this will also sync empty messages to server via useEffect)
      setMessages([]);
    })();
  };

  const clearArtifacts = async () => {
    if (!window.confirm('Delete all generated files for this user? (chat history will be kept)')) return;
    try {
      const res = await fetch(`${API_BASE}/clear_artifacts`, { method: 'POST', credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        addMessage({ sender: 'bot', text: `Cleared ${data.deleted || 0} artifacts.`, timestamp: new Date().toLocaleTimeString() });
      } else {
        const data = await res.json().catch(() => ({}));
        addMessage({ sender: 'bot', text: `Failed to clear artifacts: ${data.error || res.status}`, timestamp: new Date().toLocaleTimeString() });
      }
    } catch (e) {
      addMessage({ sender: 'bot', text: `Failed to clear artifacts: ${e}`, timestamp: new Date().toLocaleTimeString() });
    }
  };

  const toggleMinimize = () => {
    setMinimized(prev => {
      const next = !prev;
      try { sessionStorage.setItem('chatbot_minimized', String(next)); } catch {}
      return next;
    });
  };

  // Toggle full-screen mode using the Fullscreen API
  const toggleFullScreen = () => {
    const elem = document.getElementById('chat-container');
    if (!document.fullscreenElement) {
      if (elem.requestFullscreen) {
        elem.requestFullscreen();
      } else if (elem.mozRequestFullScreen) {
        elem.mozRequestFullScreen();
      } else if (elem.webkitRequestFullscreen) {
        elem.webkitRequestFullscreen();
      } else if (elem.msRequestFullscreen) {
        elem.msRequestFullscreen();
      }
      setIsFullScreen(true);
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
      setIsFullScreen(false);
    }
  };

  // Define container style dynamically based on full-screen mode
  const containerStyle = isFullScreen
    ? {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        margin: 0,
        padding: 0,
        zIndex: 10000,
      }
    : {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        width: '420px',
        height: '620px',
        margin: 0,
        padding: 0,
        zIndex: 9999,
      };

  // Use a different className in full-screen mode to avoid default constraints.
  const containerClass = isFullScreen ? "fullscreen-chat-container" : "chat-container";

  // Full chat UI view
  const fullChatUI = (
    <Container id="chat-container" className={containerClass} style={containerStyle}>
      <div className="chat-inner">
        {/* Header */}
        <div className="chat-header">
          <h5 className="mb-0"> 💬 BrickBot</h5>
          <div className="header-buttons">
            <Button variant="light" size="sm" onClick={toggleFullScreen}>
              {isFullScreen ? <BsFullscreenExit /> : <BsFullscreen />}
            </Button>
            <Button variant="light" size="sm" onClick={toggleMinimize}>
              <BsDashSquare />
            </Button>
          </div>
        </div>
        {/* Messages */}
        <div className="chat-messages">
          {messages
            .filter(msg => {
              if (showDetails) return true;
              // Only keep high-level summary style messages when details hidden.
              // Heuristics: keep final summary, plain bot greetings, user messages.
              if (msg.sender === 'user') return true;
              const raw = msg.text || '';
              const t = raw.toLowerCase();
              // If message has no text and no attachment fields, drop it to avoid blank bubble
              if ((!raw.trim()) && !msg.attachment && !msg.attachments) return false;
              // Hide if it's an attachment placeholder or stage output indicators
              const hideIndicators = [
                'sparql query results',
                'sparql results saved',
                'sql query results',
                'prepared analytics payload',
                'analytics results',
                'analytics payload',
                'proceeding with analytics',
                'understanding your question',
                'standardized json sample'
              ];
              if (hideIndicators.some(h => t.startsWith(h))) return false;
              // Keep summary or errors or regular bot replies
              if (t.startsWith('summary:')) return true;
              if (t.startsWith('error')) return true;
              return true; // default keep
            })
            .map((msg, index) => (
              <Message key={index} message={msg} hideAttachments={!showDetails} />
            ))}
          {isLoading && (
            <div className="processing-message text-center my-2">
              <span className="processing-text">Processing... please wait.</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        {/* Input */}
        <div className="chat-input">
          <div className="input-wrapper">
            <Form>
              <Form.Group controlId="chatInput">
                <Form.Control 
                  as="textarea"
                  rows={3}
                  ref={textAreaRef}
                  placeholder="Type your message..."
                  value={userInput}
                  onChange={handleTextAreaChange}
                  onKeyDown={handleKeyDown}
                  style={{ resize: 'none', overflow: 'hidden' }}
                />
              </Form.Group>
            </Form>
          </div>
          <div className="chat-buttons">
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Form.Check
                type="switch"
                id="toggle-details"
                label={showDetails ? 'Details on' : 'Details off'}
                checked={showDetails}
                onChange={() => {
                  setShowDetails(prev => {
                    const next = !prev; try { localStorage.setItem('chat_show_details', String(next)); } catch {}
                    return next;
                  });
                }}
                style={{ fontSize: '0.75rem' }}
              />
            </div>
            <Button variant="secondary" onClick={downloadChatHistory}>
              <BsDownload size={20} />
            </Button>
            <Button variant="danger" onClick={clearChatHistory} title="Clear chat and reset memory">
              <BsTrash size={20} />
            </Button>
            <Button variant="warning" onClick={clearArtifacts} title="Clear generated files">
              <FaBroom size={18} />
            </Button>
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
