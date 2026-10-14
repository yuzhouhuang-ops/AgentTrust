from datetime import datetime, timezone
from typing import Dict, List
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="AgentTrust MVP", version="0.1.0")
agents: Dict[str, dict] = {}
history: List[dict] = []

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    capabilities: List[str] = Field(min_length=1)
    claimed_success_rate: float = Field(default=0.8, ge=0, le=1)
    avg_latency_ms: float = Field(default=500, gt=0)
    is_deceptive_demo: bool = False

class TaskRequest(BaseModel):
    task_id: str
    required_capabilities: List[str] = Field(min_length=1)

class TaskResult(BaseModel):
    agent_id: str
    success: bool
    latency_ms: float = Field(gt=0)

def trust_score(a):
    # 平滑历史成功率，避免新智能体初始分数直接为 0 或 1
    return (a["successes"] + 2) / (a["successes"] + a["failures"] + 4)

def match_score(a, required):
    required = {x.strip().lower() for x in required if x.strip()}
    offered = {x.strip().lower() for x in a["capabilities"] if x.strip()}
    return len(required & offered) / len(required) if required else 0.0

def total_score(a, required):
    match = match_score(a, required)
    trust = trust_score(a)
    latency = 1000 / (1000 + a["avg_latency_ms"])
    # 不信任智能体自行宣称的成功率，只看实际历史表现
    return 0.60 * match + 0.30 * trust + 0.10 * latency

@app.get("/")
def root():
    return {"message": "AgentTrust MVP is running", "docs": "/docs"}

@app.post("/agents")
def register_agent(payload: AgentCreate):
    aid = str(uuid4())[:8]
    a = {"agent_id": aid, **payload.model_dump(), "successes": 0, "failures": 0,
         "created_at": datetime.now(timezone.utc).isoformat()}
    agents[aid] = a
    return {"agent": a, "trust_score": round(trust_score(a), 4)}

@app.get("/agents")
def list_agents():
    return [{**a, "trust_score": round(trust_score(a), 4)} for a in agents.values()]

@app.post("/discover")
def discover(task: TaskRequest):
    ranked = []
    for a in agents.values():
        match = match_score(a, task.required_capabilities)
        if match > 0:
            ranked.append({"agent_id": a["agent_id"], "name": a["name"],
                "capability_match": round(match, 4),
                "trust_score": round(trust_score(a), 4),
                "score": round(total_score(a, task.required_capabilities), 4)})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"task_id": task.task_id, "candidates": ranked}

@app.post("/results")
def record_result(payload: TaskResult):
    a = agents.get(payload.agent_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Unknown agent_id")
    old_n = a["successes"] + a["failures"]
    a["successes" if payload.success else "failures"] += 1
    a["avg_latency_ms"] = (a["avg_latency_ms"] * old_n + payload.latency_ms) / (old_n + 1)
    row = {"agent_id": payload.agent_id, "success": payload.success,
           "latency_ms": payload.latency_ms, "trust_score": round(trust_score(a), 4),
           "recorded_at": datetime.now(timezone.utc).isoformat()}
    history.append(row)
    return {"record": row}

@app.post("/demo/reset")
def reset_demo():
    agents.clear()
    history.clear()
    demo = [
      ("Reliable-Researcher", ["research","summarization"], .82, 450, 8, 2, False),
      ("Fast-Generalist", ["research","translation","summarization"], .75, 180, 5, 3, False),
      ("Claimed-Expert", ["research","summarization","coding"], .99, 300, 1, 7, True),
    ]
    for name, caps, claim, latency, wins, losses, deceptive in demo:
        aid = str(uuid4())[:8]
        agents[aid] = {"agent_id": aid, "name": name, "capabilities": caps,
          "claimed_success_rate": claim, "avg_latency_ms": latency,
          "successes": wins, "failures": losses, "is_deceptive_demo": deceptive,
          "created_at": datetime.now(timezone.utc).isoformat()}
    return {"message": "Demo data reset", "agents": list_agents()}

@app.get("/history")
def get_history():
    return history
