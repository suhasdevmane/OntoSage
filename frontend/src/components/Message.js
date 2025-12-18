// src/components/Message.js
import React from 'react';
import MediaRenderer from './MediaRenderer';

function Message({ message, hideAttachments }) {
  // Helper to render media if available
  const renderMedia = () => {
    // If an image URL is provided directly in the message object:
    if (hideAttachments) return null;
    if (message.image) {
      return <MediaRenderer media={{ type: 'image', url: message.image }} />;
    }
    // If the bot sent a custom payload with a media array
    if (message.custom && Array.isArray(message.custom.media)) {
      return message.custom.media.map((m, idx) => (
        <MediaRenderer key={idx} media={m} />
      ));
    }
    // If a single attachment exists (for example, an image, pdf, etc.)
    if (message.attachment) {
      return <MediaRenderer media={message.attachment} />;
    }
    // If multiple media objects are provided in an array
    if (message.media && Array.isArray(message.media)) {
      return message.media.map((m, idx) => <MediaRenderer key={idx} media={m} />);
    }
    return null;
  };

  const isUser = message.sender === 'user';
  const isDebug = message.type === 'debug';

  return (
    <div className={`message-row ${isUser ? 'user-message-row' : 'bot-message-row'} ${isDebug ? 'debug-message-row' : ''}`}>
      <div className={`message-bubble ${isUser ? 'user-bubble' : 'bot-bubble'} ${isDebug ? 'debug-bubble' : ''}`}>
        {!isUser && !isDebug && (
          <div className="message-label">
            <span className="bot-icon">🤖</span>
            <span className="bot-name">OntoSage</span>
          </div>
        )}
        {isUser && (
          <div className="message-label user-label">
            <span className="user-name">You</span>
          </div>
        )}
        <div className="message-content">
          <div className="message-text">{message.text}</div>
          {!hideAttachments && renderMedia()}
        </div>
        <div className="message-timestamp">{message.timestamp}</div>
      </div>
    </div>
  );
}

export default Message;