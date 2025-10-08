# T5 Training GUI - System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE (Browser)                         │
│                          http://localhost:3000                           │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 │ HTTP/REST
                                 │
                    ┌────────────▼────────────┐
                    │   React Frontend        │
                    │   SettingsTabs.js       │
                    │                         │
                    │  ┌──────────────────┐   │
                    │  │ ModelTrainingTab │   │
                    │  │                  │   │
                    │  │ ┌──────────────┐ │   │
                    │  │ │ Example Form │ │   │
                    │  │ │ - Question   │ │   │
                    │  │ │ - Sensors    │ │   │
                    │  │ │ - SPARQL     │ │   │
                    │  │ └──────────────┘ │   │
                    │  │                  │   │
                    │  │ ┌──────────────┐ │   │
                    │  │ │Examples Table│ │   │
                    │  │ │ - Edit       │ │   │
                    │  │ │ - Delete     │ │   │
                    │  │ └──────────────┘ │   │
                    │  │                  │   │
                    │  │ ┌──────────────┐ │   │
                    │  │ │Training Mon. │ │   │
                    │  │ │ - Progress   │ │   │
                    │  │ │ - Logs       │ │   │
                    │  │ │ - Status     │ │   │
                    │  │ └──────────────┘ │   │
                    │  │                  │   │
                    │  │ ┌──────────────┐ │   │
                    │  │ │Model Manager │ │   │
                    │  │ │ - List       │ │   │
                    │  │ │ - Deploy     │ │   │
                    │  │ └──────────────┘ │   │
                    │  └──────────────────┘   │
                    └────────────┬────────────┘
                                 │
                                 │ REST API Calls
                                 │
                    ┌────────────▼────────────┐
                    │   Flask Backend         │
                    │   http://localhost:6000 │
                    │                         │
                    │  ┌──────────────────┐   │
                    │  │ t5_training_bp   │   │
                    │  │                  │   │
                    │  │ API Endpoints:   │   │
                    │  │ ├─ GET /sensors  │   │
                    │  │ ├─ GET /examples │   │
                    │  │ ├─ POST/PUT/DEL  │   │
                    │  │ ├─ POST /train   │   │
                    │  │ ├─ GET /status   │   │
                    │  │ ├─ POST /deploy  │   │
                    │  │ └─ GET /models   │   │
                    │  └──────────────────┘   │
                    └─────────┬───┬───────────┘
                              │   │
            ┌─────────────────┘   └──────────────────┐
            │                                         │
            │ File I/O                                │ Subprocess
            │                                         │
   ┌────────▼────────┐                      ┌────────▼────────┐
   │  Data Files     │                      │  Python Script  │
   │                 │                      │                 │
   │ ┌─────────────┐ │                      │ quick_train.py  │
   │ │sensor_list  │ │                      │                 │
   │ │.txt         │ │                      │ ┌─────────────┐ │
   │ │(680 sensors)│ │                      │ │Load Dataset │ │
   │ └─────────────┘ │                      │ └──────┬──────┘ │
   │                 │                      │        │        │
   │ ┌─────────────┐ │                      │ ┌──────▼──────┐ │
   │ │correlation_ │ │◄─────────────────────┼─┤Tokenize Data│ │
   │ │fixes.json   │ │   Read/Write         │ └──────┬──────┘ │
   │ │(10 examples)│ │                      │        │        │
   │ └─────────────┘ │                      │ ┌──────▼──────┐ │
   │                 │                      │ │Fine-tune T5 │ │
   │ ┌─────────────┐ │                      │ │Model        │ │
   │ │Model        │ │                      │ └──────┬──────┘ │
   │ │Checkpoints  │ │                      │        │        │
   │ │             │ │                      │ ┌──────▼──────┐ │
   │ │- checkpoint-│ │◄─────────────────────┼─┤Save Model   │ │
   │ │  quick-fix  │ │   Write              │ │(checkpoint- │ │
   │ │             │ │                      │ │ quick-fix)  │ │
   │ │- checkpoint-│ │                      │ └─────────────┘ │
   │ │  3 (prod)   │ │                      │                 │
   │ │             │ │                      │ Stream stdout   │
   │ │- backups    │ │                      │ for logs        │
   │ └─────────────┘ │                      └─────────────────┘
   └─────────────────┘                               │
                                                     │
                                            ┌────────▼────────┐
                                            │  Transformers   │
                                            │  Library        │
                                            │                 │
                                            │  - T5Tokenizer  │
                                            │  - T5Model      │
                                            │  - Trainer      │
                                            └─────────────────┘
```

## Data Flow Diagrams

### 1. Add Training Example Flow

```
User Input (Form)
       │
       ▼
┌─────────────┐
│ React State │
│ - question  │
│ - sensors   │
│ - sparql    │
│ - category  │
│ - notes     │
└──────┬──────┘
       │
       │ POST /api/t5/examples
       ▼
┌─────────────────┐
│ Backend Handler │
│ - Validate data │
│ - Load JSON     │
│ - Append example│
│ - Save JSON     │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│correlation_fixes│
│.json            │
│[...existing,    │
│ new_example]    │
└──────┬──────────┘
       │
       │ Response
       ▼
┌─────────────┐
│React Update │
│- Clear form │
│- Reload list│
│- Show alert │
└─────────────┘
```

### 2. Training Flow

```
User Clicks "Start Training"
       │
       ▼
┌──────────────┐
│POST /train   │
│{epochs: 10}  │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│Backend           │
│- Create job_id   │
│- Init job state  │
│- Start thread    │
└──────┬───────────┘
       │
       ├──────────────────┐
       │                  │
       │ Return           │ Background Thread
       │ job_id           │
       │                  ▼
       │         ┌────────────────┐
       │         │Run quick_train │
       │         │.py subprocess  │
       │         └────────┬───────┘
       │                  │
       │                  │ Stream Output
       │                  ▼
       │         ┌────────────────┐
       │         │Update job:     │
       │         │- logs          │
       │         │- progress      │
       │         │- status        │
       │         └────────┬───────┘
       │                  │
       ▼                  ▼
┌──────────────┐ ┌────────────────┐
│Frontend      │ │Training        │
│- Receive     │ │Completes       │
│  job_id      │ │- Save model    │
│- Start poll  │ │- Update status │
└──────┬───────┘ └────────┬───────┘
       │                  │
       │ Poll every 2s    │
       │                  │
       │ GET /train/:id/status
       │◄─────────────────┘
       │
       ▼
┌──────────────┐
│Update UI     │
│- Progress bar│
│- Logs        │
│- Status      │
└──────────────┘
```

### 3. Model Deployment Flow

```
Training Completed
       │
       ▼
User Clicks "Deploy Model"
       │
       ▼
┌────────────────┐
│POST /deploy    │
│{job_id: "..."}│
└──────┬─────────┘
       │
       ▼
┌────────────────────────┐
│Backend                 │
│1. Validate job_id      │
│2. Check status=complete│
│3. Locate trained model │
└──────┬─────────────────┘
       │
       ▼
┌────────────────────────┐
│Backup Current Model    │
│checkpoint-3 →          │
│checkpoint-3-backup-    │
│  YYYYMMDD_HHMMSS       │
└──────┬─────────────────┘
       │
       ▼
┌────────────────────────┐
│Copy New Model          │
│checkpoint-quick-fix →  │
│checkpoint-3            │
└──────┬─────────────────┘
       │
       │ Success Response
       ▼
┌────────────────────────┐
│Frontend                │
│- Show success message  │
│- Remind restart needed │
│- Reload models list    │
└────────────────────────┘
       │
       │ User Action Required
       ▼
┌────────────────────────┐
│Go to Action Server Tab │
│Click "Restart Server"  │
│→ New model active!     │
└────────────────────────┘
```

## Component Interaction Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    React Component Lifecycle                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  componentDidMount / useEffect([])                           │
│     │                                                         │
│     ├─► loadSensors()                                        │
│     │     │                                                   │
│     │     └─► GET /api/t5/sensors                            │
│     │           │                                             │
│     │           └─► setSensors([...])                        │
│     │                                                         │
│     ├─► loadExamples()                                       │
│     │     │                                                   │
│     │     └─► GET /api/t5/examples                           │
│     │           │                                             │
│     │           └─► setExamples([...])                       │
│     │                                                         │
│     └─► loadModels()                                         │
│           │                                                   │
│           └─► GET /api/t5/models                             │
│                 │                                             │
│                 └─► setAvailableModels([...])                │
│                                                               │
│  User Interaction                                            │
│     │                                                         │
│     ├─► handleAddExample()                                   │
│     │     │                                                   │
│     │     ├─► POST /api/t5/examples                          │
│     │     │     │                                             │
│     │     │     └─► loadExamples()                           │
│     │     │                                                   │
│     │     └─► clearForm()                                    │
│     │                                                         │
│     ├─► handleStartTraining()                                │
│     │     │                                                   │
│     │     └─► POST /api/t5/train                             │
│     │           │                                             │
│     │           └─► setTrainingJobId(...)                    │
│     │                 │                                       │
│     │                 └─► Triggers polling effect            │
│     │                                                         │
│     └─► handleDeployModel()                                  │
│           │                                                   │
│           └─► POST /api/t5/deploy                            │
│                 │                                             │
│                 └─► loadModels()                             │
│                                                               │
│  useEffect([trainingJobId, trainingStatus])                  │
│     │                                                         │
│     └─► if (trainingStatus === 'running')                    │
│           │                                                   │
│           └─► setInterval(() => {                            │
│                 pollTrainingStatus(trainingJobId)            │
│               }, 2000)                                        │
│                 │                                             │
│                 └─► GET /api/t5/train/:id/status             │
│                       │                                       │
│                       └─► setTrainingProgress(...)           │
│                       └─► setTrainingLogs(...)               │
│                       └─► setTrainingStatus(...)             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## File System Structure

```
OntoBot/
│
├── microservices/
│   ├── app.py                           [Modified]
│   ├── requirements.txt                 [Existing]
│   └── blueprints/
│       └── t5_training.py               [NEW]
│
├── rasa-frontend/
│   ├── package.json                     [Modified]
│   └── src/
│       └── pages/
│           ├── SettingsTabs.js          [Modified]
│           └── ModelTrainingTab.js      [NEW]
│
├── rasa-bldg1/
│   └── actions/
│       └── sensor_list.txt              [Used by API]
│
├── Transformers/
│   └── t5_base/
│       ├── quick_train.py               [Called by API]
│       ├── GUI_TRAINING_GUIDE.md        [NEW]
│       ├── training/
│       │   └── bldg1/
│       │       └── correlation_fixes.json [Read/Write]
│       └── trained/
│           ├── checkpoint-3/             [Production]
│           ├── checkpoint-quick-fix/     [Training Output]
│           └── checkpoint-3-backup-*/    [Auto Backups]
│
└── Documentation/                        [NEW]
    ├── T5_GUI_SETUP.md
    ├── T5_GUI_IMPLEMENTATION.md
    └── QUICKSTART_GUI.md
```

## Technology Stack

```
┌───────────────────────────────────────────────────────────┐
│                       Frontend Stack                       │
├───────────────────────────────────────────────────────────┤
│ • React 19.0.0         - UI Framework                     │
│ • React Bootstrap      - UI Components                    │
│ • react-select 5.8.0   - Multi-select Dropdown           │
│ • React Router         - Navigation                       │
│ • Axios                - HTTP Client                      │
│ • Bootstrap 5.3.3      - CSS Framework                    │
└───────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────┐
│                       Backend Stack                        │
├───────────────────────────────────────────────────────────┤
│ • Flask 2.0.3          - Web Framework                    │
│ • Flask-CORS           - CORS Support                     │
│ • Python 3.x           - Runtime                          │
│ • Threading            - Background Jobs                  │
│ • Subprocess           - Script Execution                 │
│ • JSON                 - Data Storage                     │
└───────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────┐
│                       ML/Training Stack                    │
├───────────────────────────────────────────────────────────┤
│ • Transformers         - T5 Model                         │
│ • PyTorch              - Deep Learning                    │
│ • Datasets             - Data Loading                     │
│ • T5-base              - Base Model                       │
└───────────────────────────────────────────────────────────┘
```

## Security & Performance

```
┌───────────────────────────────────────────────────────────┐
│                    Current Implementation                  │
├───────────────────────────────────────────────────────────┤
│ Network:                                                   │
│ • Localhost only (3000, 6000)                             │
│ • No external access                                      │
│ • CORS enabled for local development                     │
│                                                            │
│ Authentication:                                            │
│ • None (local development)                                │
│ • No user management                                      │
│                                                            │
│ Data Validation:                                           │
│ • Basic form validation                                   │
│ • Required field checks                                   │
│ • File existence checks                                   │
│                                                            │
│ Performance:                                               │
│ • Single training job at a time                           │
│ • 2-second polling interval                               │
│ • Background thread processing                            │
│ • No request queuing                                      │
└───────────────────────────────────────────────────────────┘
```

This architecture provides a complete, maintainable solution for T5 model training with clear separation of concerns and scalable design patterns.
