from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class Criterion(BaseModel):
    name: str = Field(..., description="The name of the metric/criterion (e.g., empathy, tool_selection)")
    description: str = Field(..., description="The rubric guidelines for this criterion")
    weight: float = Field(default=1.0, description="Importance multiplier for this criterion")

class Rubric(BaseModel):
    criteria: List[Criterion]
    passing_threshold: float = Field(default=0.85, description="The minimum score required to pass this scenario")

class Message(BaseModel):
    role: str = Field(..., description="user or assistant")
    content: str

class Scenario(BaseModel):
    scenario_id: str = Field(..., description="Unique slug for this scenario")
    description: str
    category: str = Field(default="general")
    difficulty: str = Field(default="medium")
    conversation: List[Message]
    rubric: Rubric
    context: Dict[str, Any] = Field(default_factory=dict, description="Injected RAG context, databases or simulated state")

class TraceStep(BaseModel):
    step: int
    type: str = Field(..., description="system_prompt_loaded, rag_retrieval, tool_call, llm_generation, etc.")
    content: Any
    latency_ms: Optional[float] = None

class ScenarioTrace(BaseModel):
    steps: List[TraceStep] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0

class ScoreBreakdown(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str

class JudgeResponse(BaseModel):
    scores: Dict[str, ScoreBreakdown]
    overall_assessment: str
    confidence: float = Field(..., ge=0.0, le=1.0)

class ScenarioResult(BaseModel):
    scenario_id: str
    scores: Dict[str, float]
    weighted_score: float
    passed: bool
    trace: ScenarioTrace
    judge_reasonings: Dict[str, str] = Field(default_factory=dict, description="Reasoning from each judge")
