from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth_routes import router as auth_router
from app.weather_routes import router as weather_router
from app.project_intake_routes import router as project_intake_router
from app.zoning_routes import router as zoning_router
from app.projects_routes import router as projects_router
from app.activity_routes import router as activity_router

from app.graph import build_graph, ChatState


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[str]] = None  # previous messages (optional)


class ChatResponse(BaseModel):
    reply: str
    messages: List[str]


app = FastAPI(title="Project Pretzel API")

# ✅ Auth routes
# auth_routes.py already has prefix="/auth", so no extra prefix here
app.include_router(auth_router)

# ✅ Allow your Next.js dev server
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Project Intake API
app.include_router(project_intake_router, prefix="/api", tags=["project-intake"])

# Weather API
app.include_router(weather_router, prefix="/api", tags=["weather"])

# Zoning API
app.include_router(zoning_router, prefix="/api", tags=["zoning"])

# ✅ Projects API (this gives you /api/projects)
app.include_router(projects_router, prefix="/api", tags=["projects"])

# ✅ Activities API (this gives you /api/activities)
app.include_router(activity_router, prefix="/api", tags=["activities"])


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],   # <-- includes OPTIONS
    allow_headers=["*"],
)

# Build graph once for API
api_graph = build_graph()


@app.get("/")
def root():
    return {"status": "ok", "message": "LangGraph Construction Agent API running"}


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest):
    """
    Simple chat endpoint.

    - payload.message: latest user message
    - payload.history: optional previous messages (list of strings)
    """
    messages = payload.history[:] if payload.history else []
    messages.append(f"USER: {payload.message}")

    state: ChatState = {"messages": messages}

    new_state = api_graph.invoke(state)
    messages = new_state["messages"]

    last = messages[-1]
    if last.startswith("ASSISTANT:"):
        reply_text = last.replace("ASSISTANT:", "", 1).strip()
    else:
        reply_text = last

    return ChatResponse(reply=reply_text, messages=messages)
