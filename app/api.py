from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.graph import build_graph, ChatState


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[str]] = None  # previous messages (optional)


class ChatResponse(BaseModel):
    reply: str
    messages: List[str]


app = FastAPI(title="LangGraph Construction Agent")

# ✅ Allow your Next.js dev server
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

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

