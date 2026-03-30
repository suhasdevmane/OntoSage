# User Guide: Zero-Knowledge Interaction

**OntoSage** is designed for **Zero-Knowledge Interaction**, meaning you don't need to know the building's technical details (sensor IDs, ontology classes) to get answers. The system automatically adapts to your needs.

## Getting Started
1.  **Access**: Open your browser to `http://localhost:3001`.
2.  **Start Chatting**: No setup required. Just type or speak.

## Persona-Agnostic Adaptation
Unlike traditional systems that force you to choose a role, OntoSage **automatically infers** the best way to help you based on your query:

*   **Occupant Mode**: If you ask "Why is it hot?", the system assumes you are an occupant and checks comfort setpoints, offering a simple explanation.
*   **Facility Manager Mode**: If you ask "Show me the VAV damper position history," it provides detailed technical telemetry and fault diagnostics.
*   **Researcher Mode**: If you ask "What is the semantic relationship between the AHU and the VAV?", it provides the ontology graph structure.

## Interaction Modes

### 💬 Natural Language Chat
Type naturally. The system handles the complexity.

**Examples:**
*   **Comfort (Occupant)**: "It's freezing in the conference room."
*   **Diagnostics (Manager)**: "Is VAV-101 maintaining its airflow setpoint?"
*   **Sustainability (Energy)**: "How much energy did we save compared to last week?"
*   **Analytics (Data Scientist)**: "Calculate the correlation between outdoor temperature and chiller load."

### 🎤 Voice Interaction
OntoSage supports hands-free operation via **Open WebUI**:
1.  Click the **Microphone** icon.
2.  Speak your query (e.g., "Show me the active alarms").
3.  The system will transcribe your voice and respond with text and speech.

### 📊 Dynamic Visualization
When you ask for data, the system doesn't just give you a table. It automatically generates interactive **Plotly charts**:
*   **Time-Series**: Line charts for temperature/energy trends.
*   **Comparisons**: Bar charts for energy usage across rooms.
*   **Correlations**: Scatter plots for analytics.

## Tips for Best Results
*   **Be Natural**: You don't need to use specific keywords. "Room 101" works just as well as "R-101".
*   **Context Matters**: You can ask follow-up questions like "What about yesterday?" or "Compare that to the lobby."
*   **Multi-Objective**: Try asking complex questions like "Find rooms that are empty but have the lights on."

