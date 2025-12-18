"""Example queries for testing OntoSage 2.0"""

# Greeting queries
GREETINGS = [
    "Hello",
    "Hi there",
    "Good morning",
    "Hey OntoSage",
]

# SPARQL queries (ontology structure)
SPARQL_QUERIES = [
    "Show me all temperature sensors",
    "List all rooms in the building",
    "What equipment is in Room 101?",
    "Find all sensors in the HVAC zone",
    "What types of sensors are available?",
    "Show me the building structure",
    "Which zones have CO2 sensors?",
    "List all air handling units",
]

# SQL queries (time-series data)
SQL_QUERIES = [
    "What was the average temperature yesterday?",
    "Show me humidity readings from last week",
    "What's the maximum temperature recorded today?",
    "Get energy consumption for the last month",
    "Show me temperature trends over 7 days",
    "What was the minimum humidity last hour?",
    "Get all sensor readings from 2 hours ago",
]

# Analytics queries
ANALYTICS_QUERIES = [
    "Analyze temperature patterns over the last week",
    "Calculate correlation between temperature and humidity",
    "Find anomalies in energy consumption",
    "Compute average daily temperature",
    "Analyze occupancy trends",
    "Calculate energy usage statistics",
    "Find peak usage hours",
]

# Visualization queries
VISUALIZATION_QUERIES = [
    "Create a line chart of temperature over time",
    "Show me a bar chart comparing room temperatures",
    "Generate a heatmap of sensor locations",
    "Plot humidity vs temperature scatter plot",
    "Create a histogram of temperature distribution",
    "Show me a pie chart of energy usage by zone",
]

# Student persona queries
STUDENT_QUERIES = [
    "I'm a student learning about building systems",
    "Can you explain what a VAV is?",
    "How do HVAC systems work?",
    "What is the Brick Schema?",
    "Help me understand sensor types",
]

# Researcher persona queries
RESEARCHER_QUERIES = [
    "I'm a researcher studying building energy efficiency",
    "Provide detailed analysis of thermal comfort",
    "Show me correlation coefficients",
    "Generate statistical summary of sensor data",
    "What's the variance in temperature readings?",
]

# Facility manager persona queries
FACILITY_MANAGER_QUERIES = [
    "I'm a facility manager",
    "Which sensors need maintenance?",
    "Show me energy waste areas",
    "What's the current building status?",
    "Are there any abnormal readings?",
]

# Combined test scenarios
TEST_SCENARIOS = [
    {
        "persona": "student",
        "queries": [
            "Hello, I'm a student",
            "Show me temperature sensors",
            "What was the temperature yesterday?",
        ]
    },
    {
        "persona": "researcher",
        "queries": [
            "I'm a researcher",
            "List all sensors",
            "Analyze temperature trends",
            "Create a line chart",
        ]
    },
    {
        "persona": "facility_manager",
        "queries": [
            "I'm a facility manager",
            "Show me current sensor readings",
            "Are there any issues?",
        ]
    },
]
