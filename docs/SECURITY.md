# Security & Data Privacy

**OntoSage** is built with a "Privacy-First" architecture, ensuring that sensitive building data (occupancy, security feeds, energy usage) remains under your control.

## 🔒 Data Sovereignty (Local Mode)
One of the core research objectives is to enable **Zero-Knowledge Interaction** without compromising privacy.
*   **Offline Inference**: When configured with **Ollama**, all AI reasoning happens locally on your server. No data is sent to the cloud (OpenAI/Anthropic).
*   **Air-Gapped Capable**: The system can run in a fully isolated network environment, making it suitable for high-security facilities (government, defense, R&D).

## 🛡️ Sandbox Execution
To enable **Advanced Analytics**, the system generates and executes Python code on the fly. This is secured via:
*   **Docker Isolation**: The `code-executor` service runs in a container with no network access (except to the Orchestrator) and read-only access to most of the filesystem.
*   **Resource Limits**: Strict CPU and RAM limits prevent denial-of-service attacks from runaway scripts.
*   **Library Whitelisting**: Only pre-approved data science libraries (Pandas, NumPy, Plotly) are available.

## 🔑 Authentication & Access Control
*   **API Security**: All internal microservices communicate via a private Docker network.
*   **User Auth**: Open WebUI handles user authentication (Email/Password or OAuth).
*   **Database Security**:
    *   **SQL Agent**: Uses a read-only database user where possible.
    *   **Query Validation**: All generated SQL is parsed and validated to prevent SQL Injection (e.g., blocking `DROP`, `DELETE`, `INSERT`).

## 📝 Best Practices
*   **Secrets Management**: Never commit `.env` files. Use Docker Secrets in production.
*   **Regular Updates**: Keep the base images (Ollama, Python) updated to patch vulnerabilities.
*   **Network Segmentation**: Ensure the `ontobot-agentic` network is not exposed to the public internet.
