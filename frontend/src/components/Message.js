// src/components/Message.js
import React from 'react';
import FloorPlanViewer from './FloorPlanViewer';
import MediaRenderer from './MediaRenderer';

function Message({ message, hideAttachments, onSelectFloorPlanSpace }) {
  // Render interactive floor plan viewer if the message carries manifest data
  const renderFloorPlan = () => {
    const fp = message.floor_plan_structured || message.floorPlan;
    if (!fp || !fp.manifest_url) return null;
    return (
      <FloorPlanViewerWrapper
        manifestUrl={fp.manifest_url}
        onSelectSpace={onSelectFloorPlanSpace}
      />
    );
  };

  // Helper to render media if available
  const renderMedia = () => {
    if (hideAttachments) return null;
    if (message.image) {
      return <MediaRenderer media={{ type: 'image', url: message.image }} />;
    }
    if (message.custom && Array.isArray(message.custom.media)) {
      return message.custom.media.map((m, idx) => (
        <MediaRenderer key={idx} media={m} />
      ));
    }
    if (message.attachment) {
      return <MediaRenderer media={message.attachment} />;
    }
    if (message.media && Array.isArray(message.media)) {
      return message.media.map((m, idx) => <MediaRenderer key={idx} media={m} />);
    }
    return null;
  };

  const isUser = message.sender === 'user';
  const isDebug = message.type === 'debug';
  const isStreaming = message.isStreaming;
  const progressSteps = message.progressSteps || [];
  const hasText = message.text && message.text.trim();

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
          {/* Agent progress indicator — visible while streaming, before final text arrives */}
          {isStreaming && progressSteps.length > 0 && !hasText && (
            <div className="agent-progress">
              {progressSteps.map((step, i) => (
                <div
                  key={i}
                  className={`progress-step ${i === progressSteps.length - 1 ? 'progress-step-active' : 'progress-step-done'}`}
                >
                  {i === progressSteps.length - 1 ? (
                    <span className="progress-spinner" />
                  ) : (
                    <span className="progress-check">✓</span>
                  )}
                  <span>{step}</span>
                </div>
              ))}
            </div>
          )}
          {/* Thinking indicator when streaming but no steps yet */}
          {isStreaming && progressSteps.length === 0 && !hasText && (
            <div className="thinking-indicator">
              <span className="thinking-dot" />
              <span className="thinking-dot" />
              <span className="thinking-dot" />
            </div>
          )}
          {/* Message text with streaming cursor */}
          {hasText && (
            <div className="message-text">
              {message.text}
              {isStreaming && <span className="streaming-cursor" />}
            </div>
          )}
          {!hideAttachments && renderMedia()}
          {!hideAttachments && renderFloorPlan()}
        </div>
        <div className="message-timestamp">{message.timestamp}</div>
      </div>
    </div>
  );
}

// Async wrapper: fetches the manifest JSON then renders the viewer
function FloorPlanViewerWrapper({ manifestUrl, onSelectSpace }) {
  const [manifest, setManifest] = React.useState(null);

  React.useEffect(() => {
    if (!manifestUrl) return;
    fetch(manifestUrl)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.data) setManifest(data.data); })
      .catch(() => {});
  }, [manifestUrl]);

  if (!manifest) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <FloorPlanViewer
        manifest={manifest}
        onSelectSpace={onSelectSpace}
        showSensors
      />
    </div>
  );
}

export default Message;