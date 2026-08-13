from enum import StrEnum


class RuntimeKind(StrEnum):
    LLAMA_CPP = "llama_cpp"
    VLLM = "vllm"
    FAKE = "fake"


class SkillName(StrEnum):
    JAPANESE = "japanese"
    JAPANESE_CODING = "japanese_coding"
    CODING = "coding"
    SOFTWARE_ENGINEERING = "software_engineering"
    TOOL_USE = "tool_use"
    INSTRUCTION_FOLLOWING = "instruction_following"
    AGENTIC = "agentic"


class BackendState(StrEnum):
    STOPPED = "stopped"
    ALLOCATING = "allocating"
    STARTING = "starting"
    WARMING = "warming"
    READY = "ready"
    DRAINING = "draining"
    SLEEPING = "sleeping"
    STOPPING = "stopping"
    FAILED = "failed"
    DEGRADED = "degraded"
    ORPHANED = "orphaned"
    TIMEOUT = "timeout"


class QueueClass(StrEnum):
    INTERACTIVE = "interactive"
    AGENT = "agent"
    BACKGROUND = "background"
    MAINTENANCE = "maintenance"


class AgentPhase(StrEnum):
    DISCOVER = "discover"
    PLAN = "plan"
    IMPLEMENT = "implement"
    TEST = "test"
    DEBUG = "debug"
    REVIEW = "review"
    FINALIZE = "finalize"


class SchedulerMode(StrEnum):
    AUTO = "auto"
    FIXED_PROFILE = "fixed-profile"
    DRAIN = "drain"
    MAINTENANCE = "maintenance"
    SAFE_MODE = "safe-mode"
