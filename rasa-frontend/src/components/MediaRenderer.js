// src/components/MediaRenderer.js
import React from 'react';
import { BsDownload, BsBoxArrowUpRight } from 'react-icons/bs';

// Build a URL that forces download on our file server
function ensureDownloadUrl(url) {
  if (!url) return url;
  const hasQuery = url.includes('?');
  const hasDownload = /[?&]download=1/i.test(url);
  return hasDownload ? url : `${url}${hasQuery ? '&' : '?'}download=1`;
}

// Robust downloader: uses fetch+blob to trigger a download without navigating away
async function downloadFile(url, filename = 'download') {
  try {
    const downloadUrl = ensureDownloadUrl(url);
    const resp = await fetch(downloadUrl, { mode: 'cors' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename || 'download';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch (e) {
    // Fallback: open in new tab
    window.open(url, '_blank');
  }
}

// Open file in a new tab/window without forcing download
function openFile(url) {
  if (!url) return;
  window.open(url, '_blank');
}
// Map common extensions to proper MIME types for <source type="...">
function getMediaMime(kind, extension) {
  const ext = (extension || '').toLowerCase();
  const videoMap = { mp4: 'video/mp4', webm: 'video/webm', ogg: 'video/ogg' };
  const audioMap = { mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg' };
  if (kind === 'video') return videoMap[ext] || `video/${ext}`;
  if (kind === 'audio') return audioMap[ext] || `audio/${ext}`;
  return undefined;
}

// Helper: extract file extension from filename or URL
function getFileExtension(filename) {
  if (!filename) return '';
  const parts = filename.split('.');
  return parts[parts.length - 1].toLowerCase();
}

function MediaRenderer({ media }) {
  if (!media || !media.type) return null;

  // Determine a filename from media.filename or extract from media.url
  const filename = media.filename || (media.url ? media.url.split('/').pop() : 'download');
  const extension = getFileExtension(filename);

  // Render small Open + Download buttons positioned over the media element
  const renderActionButtons = () => (
    <div
      style={{
        position: 'absolute',
        top: '5px',
        right: '5px',
        display: 'flex',
        gap: '6px'
      }}
    >
      <button
        onClick={() => openFile(media.url)}
        style={{
          background: 'rgba(255,255,255,0.85)',
          border: 'none',
          cursor: 'pointer',
          padding: '4px',
          borderRadius: '50%'
        }}
        title="Open"
      >
        <BsBoxArrowUpRight size={16} />
      </button>
      <button
        onClick={() => downloadFile(media.url, filename)}
        style={{
          background: 'rgba(255,255,255,0.85)',
          border: 'none',
          cursor: 'pointer',
          padding: '4px',
          borderRadius: '50%'
        }}
        title="Download"
      >
        <BsDownload size={16} />
      </button>
    </div>
  );

  // Container style to wrap media and position download button
  const containerStyle = {
    position: 'relative',
    display: 'inline-block',
    marginTop: '10px'
  };

  switch (media.type) {
    case 'text':
      return (
        <div style={containerStyle}>
          <pre style={{ maxWidth: '100%', overflowX: 'auto' }}>
            {media.content}
          </pre>
          {renderActionButtons()}
        </div>
      );

    case 'image':
      return (
        <div style={containerStyle}>
          <img src={media.url} alt="media" style={{ maxWidth: '100%' }} />
          {renderActionButtons()}
        </div>
      );

    case 'pdf':
      return (
        <div style={containerStyle}>
          <iframe
            src={media.url}
            title="PDF Viewer"
            style={{ width: '100%', height: 'min(60vh, 520px)', border: 'none' }}
          />
          {renderActionButtons()}
        </div>
      );

    case 'chart':
      return (
        <div style={containerStyle}>
          <iframe
            src={media.url}
            title="Chart"
            style={{ width: '100%', height: 'min(60vh, 520px)', border: 'none' }}
          />
          {renderActionButtons()}
        </div>
      );

    case 'video':
      // For video, support various formats (mp4, flv, mkv, 3gp)
      return (
        <div style={containerStyle}>
          <video controls style={{ maxWidth: '100%' }}>
            <source src={media.url} type={getMediaMime('video', extension)} />
            Your browser does not support the video tag.
          </video>
          {renderActionButtons()}
        </div>
      );

    case 'audio':
      return (
        <div style={containerStyle}>
          <audio controls style={{ maxWidth: '100%' }}>
            <source src={media.url} type={getMediaMime('audio', extension)} />
            Your browser does not support the audio element.
          </audio>
          {renderActionButtons()}
        </div>
      );

    // For non-previewable document types (DOC, XLS, PPT, ZIP, PSD, DXF, SQL, etc.)
    case 'doc':
    case 'docx':
    case 'xls':
    case 'xlsx':
    case 'ppt':
    case 'pptx':
    case 'zip':
    case 'psd':
    case 'dxf':
    case 'sql':
    case 'json':
    case 'xml':
    case 'log':
    case 'txt':
    case 'csv':
    case 'html':
      return (
        <div style={containerStyle}>
          <div style={{
            padding: '0px', // Reduced padding from 20px to 10px
            // border: '1px solid #ccc',
            borderRadius: '1px',
            textAlign: 'center',
            minWidth: '100px',
            maxHeight: '120px', // Added maximum height
            height: '60px',    // Added fixed height
            overflow: 'hidden', // Prevent content from spilling out
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center'
          }}>
            {/* Generic file icon, can be replaced with a specific icon */}
            <div style={{ fontSize: '12px' }}>📄</div> {/* Reduced from 32px */}
            <div style={{ fontSize: '10px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{filename}</div>
            <div style={{ fontSize: '10px', color: '#888' }}>Preview not available</div>
          </div>
          {renderActionButtons()}
        </div>
      );

    case 'link':
      return (
        <div style={containerStyle}>
          <a href={media.url} target="_blank" rel="noopener noreferrer">
            {media.url}
          </a>
          {renderActionButtons()}
        </div>
      );

    default:
      return (
        <div style={containerStyle}>
          <div>Unsupported media type: {media.type}</div>
          {renderActionButtons()}
        </div>
      );
  }
}

export default MediaRenderer;
