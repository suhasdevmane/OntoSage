import React, { useState, useEffect } from 'react';
import { ListGroup, Button, Spinner, Alert, Badge } from 'react-bootstrap';
import { FaHistory, FaPlus, FaTrash, FaCommentAlt } from 'react-icons/fa';
import axios from 'axios';

const ConversationHistory = ({ 
  userId, 
  currentConversationId, 
  onSelectConversation, 
  onNewConversation, 
  onDeleteConversation 
}) => {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(currentConversationId);

  // Update local state when prop changes
  useEffect(() => {
    setSelectedId(currentConversationId);
  }, [currentConversationId]);

  // Load conversations when component mounts or userId changes
  useEffect(() => {
    if (userId) {
      loadConversations();
    }
  }, [userId]);

  const loadConversations = async () => {
    setLoading(true);
    setError(null);
    try {
      // Use the new lightweight endpoint that returns metadata only
      const response = await axios.get(`http://localhost:8000/conversations/${userId}`);
      
      // API returns { success: true, data: { conversations: [...] } }
      const conversationsList = response.data.data?.conversations || response.data.conversations || [];

      // Sort by updated_at desc
      const sorted = conversationsList.sort((a, b) => {
        return new Date(b.updated_at) - new Date(a.updated_at);
      });
      
      setConversations(sorted);
    } catch (err) {
      console.error("Error loading history:", err);
      setError("Failed to load history");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e, convId) => {
    e.stopPropagation(); // Prevent triggering selection
    if (window.confirm('Are you sure you want to delete this conversation?')) {
      try {
        await axios.delete(`http://localhost:8000/history/${userId}/${convId}`);
        
        // Remove from local state
        setConversations(prev => prev.filter(c => c.conversation_id !== convId));
        
        // Notify parent if needed
        if (onDeleteConversation) {
          onDeleteConversation(convId);
        }
        
        // If we deleted the current one, trigger new conversation
        if (selectedId === convId && onNewConversation) {
          onNewConversation();
        }
      } catch (err) {
        console.error("Error deleting conversation:", err);
        alert("Failed to delete conversation");
      }
    }
  };

  const formatTime = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  if (loading && conversations.length === 0) {
    return (
      <div className="text-center p-3">
        <Spinner animation="border" size="sm" />
        <p className="mt-2 text-muted" style={{ fontSize: '0.9rem' }}>Loading conversations...</p>
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="warning" className="m-3" style={{ fontSize: '0.9rem' }}>
        <strong>⚠️ Error</strong>
        <p className="mb-0 mt-1">{error}</p>
        <Button variant="outline-warning" size="sm" className="mt-2" onClick={loadConversations}>
          Retry
        </Button>
      </Alert>
    );
  }

  return (
    <div className="conversation-history d-flex flex-column" style={{ height: '100%' }}>
      {/* Header / New Chat Button */}
      <div className="p-3 border-bottom bg-light">
        <Button 
          variant="primary" 
          className="w-100 d-flex align-items-center justify-content-center gap-2"
          onClick={() => {
            if (onNewConversation) onNewConversation();
          }}
        >
          <FaPlus size={12} /> New Chat
        </Button>
      </div>

      {/* List */}
      <div className="flex-grow-1 overflow-auto">
        {conversations.length === 0 ? (
          <div className="text-center p-4 text-muted">
            <FaCommentAlt size={24} className="mb-2 opacity-50" />
            <p className="small">No history yet.</p>
          </div>
        ) : (
          <ListGroup variant="flush">
            {conversations.map((conv) => (
              <ListGroup.Item
                key={conv.conversation_id}
                action
                active={selectedId === conv.conversation_id}
                onClick={() => onSelectConversation(conv.conversation_id)}
                className="border-0 border-bottom py-3 px-3 position-relative conversation-item"
                style={{ cursor: 'pointer' }}
              >
                <div className="d-flex justify-content-between align-items-start mb-1">
                  <div className="fw-bold text-truncate pe-2" style={{ maxWidth: '85%' }}>
                    {conv.title || 'New Conversation'}
                  </div>
                  {selectedId === conv.conversation_id && (
                    <Badge bg="light" text="dark" className="border">Active</Badge>
                  )}
                </div>
                
                <div className="d-flex justify-content-between align-items-center">
                  <small className="text-muted">
                    {formatTime(conv.updated_at)}
                  </small>
                  
                  <Button 
                    variant="link" 
                    className="p-0 text-muted delete-btn" 
                    style={{ opacity: 0.5 }}
                    onClick={(e) => handleDelete(e, conv.conversation_id)}
                    title="Delete conversation"
                  >
                    <FaTrash size={12} />
                  </Button>
                </div>
              </ListGroup.Item>
            ))}
          </ListGroup>
        )}
      </div>
    </div>
  );
};

export default ConversationHistory;
