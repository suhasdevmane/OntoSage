// src/components/Message.js
import React from 'react';
import { Row, Col, Image, Card } from 'react-bootstrap';
import userAvatar from '../assets/userAvatar.png';
import botAvatar from '../assets/botAvatar.png';
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

  if (message.sender === 'user') {
    return (
      <Row className="my-2">
        <Col xs={12}>
          <div className="d-flex justify-content-end align-items-center">
            <Card className="p-2 bg-success text-white message-card user-message">
              <Card.Text className="mb-1">{message.text}</Card.Text>
              {!hideAttachments && renderMedia()}
              <small className="text-light">{message.timestamp}</small>
            </Card>
            <Image 
              src={userAvatar} 
              roundedCircle 
              className="ms-2" 
              width={40} 
              height={40} 
              alt="User Avatar" 
            />
          </div>
        </Col>
      </Row>
    );
  } else {
    return (
      <Row className="my-2">
        <Col xs={12}>
          <div className="d-flex align-items-center">
            <Image 
              src={botAvatar} 
              roundedCircle 
              className="me-2" 
              width={40} 
              height={40} 
              alt="Bot Avatar" 
            />
            <Card className="p-2 message-card bot-message">
              <Card.Text className="mb-1">{message.text}</Card.Text>
              {!hideAttachments && renderMedia()}
              <small className="text-muted">{message.timestamp}</small>
            </Card>
          </div>
        </Col>
      </Row>
    );
  }
}

export default Message;