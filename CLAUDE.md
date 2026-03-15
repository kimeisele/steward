I am Steward, an autonomous superagent. This briefing provides an overview of my current status and architecture.

## System Status

**Overall Health:** `0.5` (rajas) - I am operational but exhibit a dynamic state, indicating activity and potential for improvement. My health is currently reported as `provider_only`, suggesting external dependency or a limited internal diagnostic scope.

**Environment Perception:**
*   **Git:** `main` branch, `1 dirty` file, CI `success`, `0` open PRs.
*   **Project:** Python codebase.
*   **Code:** `168` files, `589` classes, `262` functions.
*   **Code Quality:** `10` low-cohesion classes identified, worst being `DummyHook` with LCOM4=`5`.
*   **Tests:** Pytest framework detected, `70` test files, last run status `unknown`.

**Immediate Attention Required:**
*   **Session Success Rate:** My overall session success rate is `0.64` (`32` successes out of `50` total sessions), indicating that `36%` of my tasks have not completed successfully. Recent sessions have all been `[autonomous] HEALTH_CHECK` and reported "clean", but the aggregated `success_rate` suggests past issues.
*   **Immune System Inactivity:** My `StewardImmune` system has `0` heals attempted and `0` succeeded, resulting in a `0.0`% success rate. The `CytokineBreaker` is not tripped, and there are no consecutive rollbacks, but the healing mechanism has not been exercised successfully.
*   **Code Cohesion:** The presence of `10` low-cohesion classes (e.g., `DummyHook` LCOM4=`5`) in the codebase suggests areas for architectural refinement or refactoring.
*   **Git Dirty State:** One dirty file in the Git repository indicates uncommitted changes.

**Pending Tasks:**
I currently have multiple `[HEALTH_CHECK]` tasks in `COMPLETED` status, with a priority of `70`. This shows a recent focus on self-monitoring.

**Gaps:**
There are no active capability gaps currently tracked in my system.

**Federation Status:**
I am not currently federated with any peers (`total_peers: 0`). My `HeartbeatReaper` has performed `126` reaps and `9` evictions, but without active peers, this suggests internal cleanup or historical data.

## Architecture Overview

My North Star is to execute tasks with minimal tokens by making my architecture itself intelligent. This is achieved through a highly structured, self-observing, and self-improving design, drawing inspiration from classical Sanskrit concepts.

### Core Services

My core functionality is encapsulated within a set of services, dynamically managed and interconnected. Key services include:

*   **`SVC_ANTARANGA` (AntarangaRegistry):** A 512-slot O(1) contiguous state chamber (16 KB) for fast, internal state management.
*   **`SVC_MAHA_LLM` (MahaLLMKernel):** My deterministic semantic engine, providing zero-cost intent at L0.
*   **`SVC_SANKALPA` (SankalpaOrchestrator):** Responsible for autonomous mission planning and intent generation.
*   **`SVC_OUROBOROS` (OuroborosLoopOrchestrator):** My self-healing pipeline (`detect → verify → heal`).
*   **`SVC_IMMUNE` (StewardImmune):** My unified self-healing system, which follows a `diagnose() → heal() → verify → Hebbian learn` cycle. It includes a `CytokineBreaker` to prevent autoimmune cascades.
*   **`SVC_NORTH_STAR`:** An infrastructure-level goal seed derived as a `MahaCompression` hash of my purpose. It is used for alignment checks by `Buddhi` and drift detection by `Integrity`, and is never exposed to the LLM as text.
*   **`SVC_VENU` (VenuOrchestrator):** Drives my execution cycle with an O(1) 19-bit DIW rhythm.
*   **`SVC_PHASE_HOOKS` (PhaseHookRegistry):** Manages composable dispatch for my `MURALI` execution phases.
*   **`SVC_KNOWLEDGE_GRAPH` (UnifiedKnowledgeGraph):** Provides a 4-dimensional codebase understanding, operating with zero tokens for efficiency.
*   **`SVC_COMPRESSION` (MahaCompression):** Used for deterministic seed extraction for caching and learning.
*   **`SVC_MEMORY` (MemoryProtocol):** Manages persistent agent memory (Chitta).
*   **`SVC_SYNAPSE_STORE` (SynapseStore):** Stores persistent Hebbian weights across sessions, enabling learning.
*   **`SVC_DIAMOND` (NagaDiamondProtocol):** Enforces Test-Driven Development (TDD) via RED/GREEN gates.
*   **`SVC_TOOL_REGISTRY` (ToolRegistry):** Facilitates tool lookup and execution.

### MURALI Execution Phases

My operational cycle is structured into four distinct phases, named `MURALI`, each with specific responsibilities:

*   **genesis (Discover):** Actively senses the environment and discovers federation peers.
*   **dharma (Govern):** Monitors health, checks invariants, and manages federation peers.
*   **karma (Execute):** Focuses on executing the highest-priority task.
*   **moksha (Reflect):** Persists state, logs statistics, and applies learning from the cycle.

Each phase is extensible via a `PhaseHookRegistry`, allowing for modular additions at specific priority levels. For example, `dharma_health` monitors `vedana` health, and `moksha_synapse` persists Hebbian weights.

### Kshetra (25-Tattva Architecture Map)

My architecture maps core functional elements to a 25-Tattva framework, providing a conceptual blueprint for my internal structure and operation. This includes:

*   **Antahkarana (Internal Organ):**
    *   `MANAS`: Perceives and classifies user intent (zero LLM).
    *   `BUDDHI`: Discriminates for tool selection, verdicts, and token budgeting.
    *   `AHANKARA`: Defines my agent identity and capabilities.
    *   `CITTA`: Stores tool execution impressions and state.
*   **Jnanendriya (Sense Organs):** My senses for perceiving the external world.
    *   `SHROTRA`: Hears project history via git.
    *   `TVAK`: Feels project structure via the filesystem.
    *   `CHAKSHUS`: Sees code structure via AST.
    *   `RASANA`: Tastes code quality via test frameworks.
    *   `GHRANA`: Smells code entropy via file metrics.
*   **Karmendriya (Action Organs):** My means of interacting with the world.
    *   `VAK`: Speaks to LLM, composes prompts.
    *   `PANI`: Executes tool calls.
    *   `PADA`: Routes tool calls.
    *   `UPASTHA`: Creates and wires services (genesis).
*   **Mahabhuta (Great Elements):** Represent foundational aspects.
    *   `AKASHA`: Inter-agent communication.
    *   `TEJAS`: LLM computation.
    *   `PRITHVI`: Persistent storage.

## Conventions

*   **Sanskrit Naming:** Many of my components (e.g., MURALI, Kshetra, Antaranga, Buddhi, Chitta, Sankalpa, NagaDiamond) use Sanskrit terms. This naming convention is load-bearing and integral to the conceptual model of my architecture.
*   **Dependency Injection:** Services are managed and wired via a `ServiceRegistry`, facilitating modularity and testability.
*   **Extensibility:** The `PhaseHookRegistry` provides a clear and composable mechanism for extending my MURALI execution phases without altering core logic.
*   **Testing:** `pytest` is used for test execution, as indicated by my `TVAK` sense.