# User Guide

This guide explains how to interact with OntoSage 2.0 through the chat UI.

## Getting Started
1.  **Login**: Use your credentials to access the dashboard.
2.  **Select Persona**: Choose a persona (Student, Researcher, Facility Manager) to tailor the AI's responses.
3.  **Select Building**: Pick the building you want to query from the dropdown.

## Personas
*   **Student**: The AI acts as a tutor, explaining concepts and terminology simply.
*   **Researcher**: The AI provides detailed, ontology-driven explanations and data provenance.
*   **Facility Manager**: The AI focuses on operational status, alarms, KPIs, and actionable insights.

## Interaction Modes

### 💬 Chat
Type your questions naturally. The system understands context, so you can ask follow-up questions.

**Examples:**
*   **General**: "Explain the HVAC system in Building 1"
*   **Structural (SPARQL)**: "List all CO₂ sensors on Floor 2"
*   **Data (SQL)**: "What was the average temperature in Room 101 last week?"
*   **Analytics**: "Is there a correlation between occupancy and temperature in Room 101?"
*   **Visualization**: "Plot hourly electricity usage for yesterday"

### 🎤 Voice Input
1.  Click the **Microphone** icon.
2.  Speak your query clearly (e.g., "Show me the active alarms").
3.  Click stop to send. The system will transcribe and process your request.

### 🏢 3D Digital Twin
The 3D viewer on the right side of the screen is interactive:
*   **Highlighting**: When you ask about a specific room or sensor, the viewer will automatically zoom in and highlight it.
*   **Navigation**: You can manually rotate, zoom, and pan to explore the building structure.

## Tips for Best Results
*   **Be Specific**: Mention specific room numbers (e.g., "Room 101") or equipment names if known.
*   **Time Ranges**: For data queries, specify a time range (e.g., "last 24 hours", "last month").
*   **Follow-up**: If an answer is incomplete, ask "Can you elaborate?" or "Show me the data for the previous week too".

