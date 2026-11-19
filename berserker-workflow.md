
# Berserker — Automation Workflow

A simplified overview of the Android automation process.

```mermaid
flowchart TD
    A([Start Berserker]) --> B[Initialize Automation]
    B --> C[Connect to Android Device]
    C --> D{Device Connected?}

    D -->|No| E[Retry Connection]
    E --> C

    D -->|Yes| F[Load Fixture List]
    F --> G[Select Next Fixture]
    G --> H[Check Application State]

    H --> I{Logged In?}
    I -->|No| J[Handle Login]
    I -->|Yes| K[Navigate to Target Task]
    J --> K

    K --> L[Execute Automation]
    L --> M[Monitor Execution]
    M --> N[Capture Result]
    N --> O[Record Result and Timing]

    O --> P{More Fixtures?}
    P -->|Yes| G
    P -->|No| Q[Generate Execution Summary]
    Q --> R([End])
```

## Key workflow stages

1. **Initialization** — Prepare the automation environment.
2. **Device connection** — Establish communication with Android.
3. **Fixture selection** — Choose the next task to execute.
4. **State verification** — Check application and login state.
5. **Task execution** — Perform the required automation.
6. **Monitoring** — Observe execution and capture timing.
7. **Reporting** — Record results and summarize performance.
