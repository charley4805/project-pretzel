import os
import re
import math
from typing import TypedDict, List, Optional, Dict, Any
import uuid
from uuid import UUID

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Project, ProjectMember, Role, ProjectDocument


# Load environment variables once when this module is imported
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

if not OPENAI_API_KEY:
    raise ValueError(
        "OPENAI_API_KEY is not set. Add it to your .env file as OPENAI_API_KEY=..."
    )


# ---------- GRAPH STATE ----------

class ChatState(TypedDict):
    # Conversation history in "USER: ..." / "ASSISTANT: ..." format
    messages: List[str]
    # Active project this chat is about (UUID as string)
    projectId: Optional[str]
    # who is asking
    userId: Optional[str]
    # their role in that project (e.g., "PROJECT_MANAGER")
    roleKey: Optional[str]


# Create LLM client (shared by all nodes)
llm = ChatOpenAI(
    model=MODEL,
    api_key=OPENAI_API_KEY,
)


# ---------- Construction Measurement Helper (feet/inches) ----------

def parse_feet_inches(text: str) -> Optional[float]:
    """
    Parse a construction-style length from text and return total inches.
    Supported examples:
        "9 ft 7 in"
        "9 feet 7 inches"
        "9' 7\""
        "10'"
        "14 in"
    """
    t = text.lower()

    # Handle patterns like: 9' 7"  or  9'7"
    combo = re.search(r"(\d+(?:\.\d+)?)\s*'\s*(\d+(?:\.\d+)?)\s*\"", t)
    if combo:
        feet = float(combo.group(1))
        inches = float(combo.group(2))
        return feet * 12 + inches

    # General feet / inches matches
    feet_match = re.search(r"(\d+(?:\.\d+)?)\s*(feet|foot|ft|')", t)
    inch_match = re.search(r"(\d+(?:\.\d+)?)\s*(inches|inch|in|\")", t)

    feet = float(feet_match.group(1)) if feet_match else 0.0
    inches = float(inch_match.group(1)) if inch_match else 0.0

    if feet == 0.0 and inches == 0.0:
        # Nothing found
        return None

    return feet * 12 + inches


def construction_measurement_node(state: ChatState) -> ChatState:
    """
    Node that acts as a construction-specific calculator for measurements.
    It looks at the last USER message, tries to parse a feet/inches value,
    and responds with a handy breakdown.
    """
    last = state["messages"][-1]
    # Strip "USER:" prefix if present
    if last.lower().startswith("user:"):
        text = last[5:].strip()
    else:
        text = last

    total_inches = parse_feet_inches(text)

    if total_inches is None:
        reply = (
            "I tried to treat that as a construction measurement, but couldn't parse it.\n"
            "Try something like:\n"
            " - 9 ft 7 in\n"
            " - 9' 7\"\n"
            " - 10 feet\n"
            " - 14 inches"
        )
    else:
        feet = int(total_inches // 12)
        inches = total_inches % 12
        feet_inches_str = f"{feet}' {inches:.2f}\""

        reply = (
            "Here's your construction measurement breakdown:\n"
            f" - Total inches: {total_inches:.2f} in\n"
            f" - Feet & inches: {feet_inches_str}\n"
        )

    new_messages = state["messages"] + [f"ASSISTANT: {reply}"]
    return {
        "messages": new_messages,
        "projectId": state.get("projectId"),
        "userId": state.get("userId"),
        "roleKey": state.get("roleKey"),
    }


# ---------- Board-Foot Helper ----------

def parse_board_foot(text: str) -> Optional[dict]:
    """
    Parse a simple board-foot request.

    Expected patterns (examples):
        - "2x10x16"
        - "10 pieces of 2x6x12"
        - "calculate board feet for 20 boards 2x8x14"

    Interpretation:
        thickness (in) x width (in) x length (ft) [per board]
        board feet per board = (T * W * L) / 12
        total board feet = board feet per board * quantity
    """
    t = text.lower()

    # Find dimensions like 2x10x16
    dim_match = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", t
    )
    if not dim_match:
        return None

    thickness = float(dim_match.group(1))
    width = float(dim_match.group(2))
    length_feet = float(dim_match.group(3))

    # Find quantity (optional)
    qty_match = re.search(
        r"(\d+)\s*(pieces|piece|pcs|boards|planks|qty|quantity)", t
    )
    if qty_match:
        qty = int(qty_match.group(1))
    else:
        qty = 1

    bf_per_board = (thickness * width * length_feet) / 12.0
    total_bf = bf_per_board * qty

    return {
        "thickness": thickness,
        "width": width,
        "length_feet": length_feet,
        "quantity": qty,
        "bf_per_board": bf_per_board,
        "total_bf": total_bf,
    }


def board_foot_node(state: ChatState) -> ChatState:
    """
    Node that calculates board feet for dimensional lumber.
    """
    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        text = last[5:].strip()
    else:
        text = last

    parsed = parse_board_foot(text)

    if not parsed:
        reply = (
            "I tried to treat that as a board-foot calculation but couldn't parse it.\n"
            "Try something like:\n"
            " - 2x10x16\n"
            " - 10 boards of 2x6x12\n"
            " - calculate board feet for 20 pieces 2x8x14"
        )
    else:
        thickness = parsed["thickness"]
        width = parsed["width"]
        length_feet = parsed["length_feet"]
        quantity = parsed["quantity"]
        bf_per_board = parsed["bf_per_board"]
        total_bf = parsed["total_bf"]

        reply = (
            "Board-foot calculation:\n"
            f" - Dimensions per board: {thickness} in x {width} in x {length_feet} ft\n"
            f" - Quantity: {quantity}\n"
            f" - Board feet per board: {bf_per_board:.2f} bf\n"
            f" - Total board feet: {total_bf:.2f} bf\n"
        )

    new_messages = state["messages"] + [f"ASSISTANT: {reply}"]
    return {
        "messages": new_messages,
        "projectId": state.get("projectId"),
        "userId": state.get("userId"),
        "roleKey": state.get("roleKey"),
    }


# ---------- Sheet Count Helper (Tool 1) ----------

def parse_area_sqft(text: str) -> Optional[float]:
    """
    Try to parse an area in square feet.

    Supports:
        - "720 sq ft", "720 sqft", "720 square feet", "720 sf"
        - simple LxW: "12x20", "12 x 20" (interpreted as feet)
    """
    t = text.lower()

    # Explicit square feet
    m = re.search(r"(\d+(?:\.\d+)?)\s*(square feet|sq ft|sqft|sf)", t)
    if m:
        return float(m.group(1))

    # Length x Width (e.g. 12x20)
    m = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)", t)
    if m:
        length = float(m.group(1))
        width = float(m.group(2))
        return length * width

    return None


def parse_sheet_area(text: str) -> float:
    """
    Determine sheet size in square feet.

    Defaults to 4x8 (32 sqft).
    If text contains something like "4x10 sheets" or "5x8 drywall",
    uses that dimension instead.
    """
    t = text.lower()
    default_area = 4.0 * 8.0

    # Look for something that looks like sheet dimensions near sheet-related words
    dim_match = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?).*(sheet|sheets|drywall|plywood|osb|panel|panels)",
        t,
    )
    if dim_match:
        w = float(dim_match.group(1))
        l = float(dim_match.group(2))
        return w * l

    return default_area


def sheet_count_node(state: ChatState) -> ChatState:
    """
    Node that estimates how many sheets are needed to cover an area.
    Assumes flat coverage (no waste factor, corners, openings, etc.).
    """
    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        text = last[5:].strip()
    else:
        text = last

    area = parse_area_sqft(text)
    if area is None:
        reply = (
            "I tried to treat that as a sheet-count question but couldn't parse the area.\n"
            "Examples I understand:\n"
            " - How many 4x8 sheets for 720 sq ft?\n"
            " - Sheets needed for 12x20 room (use '12x20')\n"
            " - 350 square feet of drywall, 4x10 sheets\n"
        )
    else:
        sheet_area = parse_sheet_area(text)
        raw_count = area / sheet_area
        sheets_needed = math.ceil(raw_count)

        reply = (
            "Sheet count estimate:\n"
            f" - Area to cover: {area:.2f} sq ft\n"
            f" - Sheet size area: {sheet_area:.2f} sq ft\n"
            f" - Raw sheet count (no rounding): {raw_count:.2f}\n"
            f" - Recommended sheets (rounded up): {sheets_needed}\n"
            "Note: This does not include waste, cuts, or openings."
        )

    new_messages = state["messages"] + [f"ASSISTANT: {reply}"]
    return {
        "messages": new_messages,
        "projectId": state.get("projectId"),
        "userId": state.get("userId"),
        "roleKey": state.get("roleKey"),
    }


# ---------- Material Cost Estimator (Tool 5) ----------

def parse_price(text: str) -> Optional[float]:
    """
    Parse a price value from text, e.g. '$14', '14 per sheet', '$2.10 per bf'.
    Returns just the numeric price.
    """
    t = text.lower()

    # Look for $xx.xx
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1))

    # Look for 'xx per ...'
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:per|/)\s*(sheet|sheets|bf|board feet|sqft|square foot|unit|board|piece)", t)
    if m:
        return float(m.group(1))

    return None


def parse_quantity_with_unit(text: str) -> Optional[int]:
    """
    Try to parse a quantity of units from text, e.g.:
        - '40 sheets'
        - '16 boards'
        - '200 bf'
    Falls back to the first integer if nothing else is found.
    """
    t = text.lower()
    m = re.search(
        r"(\d+)\s*(sheets|sheet|boards|board|pieces|piece|units|unit|bf|board feet|sqft|square feet)",
        t,
    )
    if m:
        return int(m.group(1))

    # Fallback: first number at all
    m = re.search(r"(\d+)", t)
    if m:
        return int(m.group(1))

    return None


def material_cost_node(state: ChatState) -> ChatState:
    """
    Estimate material cost based on:
      - board-foot dimensions + price per bf
      - OR quantity + price per unit (sheets/boards/etc.)

    Role-aware behavior:
      - PROJECT_MANAGER and ESTIMATOR roles get full cost breakdown
      - Others are told that detailed cost visibility is restricted
    """
    role_key = state.get("roleKey")

    allowed_roles_for_cost = {"PROJECT_MANAGER", "ESTIMATOR"}
    if role_key not in allowed_roles_for_cost:
        reply = (
            "I can help you with quantities and measurements, but detailed "
            "material cost estimates are restricted to the Project Manager "
            "or Estimator. Please ask them for the exact cost breakdown."
        )
        return {
            "messages": state["messages"] + [f"ASSISTANT: {reply}"],
            "projectId": state.get("projectId"),
            "userId": state.get("userId"),
            "roleKey": role_key,
        }

    # --- existing cost logic below this line ---

    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        text = last[5:].strip()
    else:
        text = last

    t = text.lower()

    price = parse_price(text)

    # Try a board-foot based query first
    bf_info = parse_board_foot(text)
    cost_details: Dict[str, Any] = {}

    if bf_info and ("bf" in t or "board foot" in t or "board feet" in t):
        if price is None:
            reply = (
                "I detected a board-foot style request but couldn't parse a price.\n"
                "Try something like:\n"
                " - Cost for 16 boards of 2x10x16 at $2.10 per bf\n"
            )
        else:
            total_bf = bf_info["total_bf"]
            total_cost = total_bf * price
            cost_details = {
                "mode": "board_foot",
                "total_bf": total_bf,
                "price_per_bf": price,
                "total_cost": total_cost,
                "quantity": bf_info["quantity"],
                "thickness": bf_info["thickness"],
                "width": bf_info["width"],
                "length_feet": bf_info["length_feet"],
            }
            reply = (
                "Material cost estimate (board feet):\n"
                f" - Dimensions per board: {bf_info['thickness']} in x {bf_info['width']} in x {bf_info['length_feet']} ft\n"
                f" - Quantity: {bf_info['quantity']}\n"
                f" - Total board feet: {total_bf:.2f} bf\n"
                f" - Price per bf: ${price:.2f}\n"
                f" - Estimated material cost: ${total_cost:.2f}\n"
            )
    else:
        # Generic quantity * unit price
        qty = parse_quantity_with_unit(text)
        if price is None or qty is None:
            reply = (
                "I tried to treat that as a material cost question but couldn't parse "
                "both a quantity and a price.\n"
                "Examples I understand:\n"
                " - Cost for 40 sheets at $14 each\n"
                " - 25 boards at $8.50 per board\n"
                " - 200 sqft at $1.20 per sqft\n"
                " - 16 boards of 2x10x16 at $2.10 per bf\n"
            )
        else:
            total_cost = qty * price
            cost_details = {
                "mode": "unit",
                "quantity": qty,
                "price_per_unit": price,
                "total_cost": total_cost,
            }
            reply = (
                "Material cost estimate:\n"
                f" - Quantity: {qty}\n"
                f" - Price per unit: ${price:.2f}\n"
                f" - Estimated material cost: ${total_cost:.2f}\n"
            )

    new_messages = state["messages"] + [f"ASSISTANT: {reply}"]
    return {
        "messages": new_messages,
        "projectId": state.get("projectId"),
        "userId": state.get("userId"),
        "roleKey": role_key,
    }


# ---------- Project Document RAG Helpers ----------

def _fetch_project_documents(project_id: str) -> List[ProjectDocument]:
    """
    Load all documents for a given project UUID string.
    Returns an empty list if project_id is invalid or no docs exist.
    """
    try:
        project_uuid = UUID(project_id)
    except (ValueError, TypeError):
        return []

    db: Session = SessionLocal()
    try:
        docs = (
            db.query(ProjectDocument)
            .filter(ProjectDocument.project_id == project_uuid)
            .order_by(ProjectDocument.created_at.desc())
            .all()
        )
        return docs
    finally:
        db.close()


def _score_doc_relevance(doc: ProjectDocument, query: str) -> int:
    """
    Very simple relevance scoring:
    - tokenizes the query
    - counts how many query tokens appear in title+content (case-insensitive)
    """
    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        return 0

    text = f"{doc.title}\n{doc.content}".lower()
    score = 0
    for token in query_tokens:
        if token in text:
            score += 1
    return score


def _get_top_project_docs(
    project_id: Optional[str],
    question: str,
    k: int = 3,
) -> List[tuple[str, str]]:
    """
    Return up to k (title, content) tuples of the most relevant docs
    for this project + question, using the simple keyword-overlap scorer.
    """
    if not project_id:
        return []

    docs = _fetch_project_documents(project_id)
    if not docs:
        return []

    scored: List[tuple[int, ProjectDocument]] = []
    for d in docs:
        score = _score_doc_relevance(d, question)
        if score > 0:
            scored.append((score, d))

    if not scored:
        return []

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_docs = [d for _, d in scored[:k]]
    return [(d.title, d.content) for d in top_docs]


# ---------- Assistant Node (general chat with project RAG) ----------

def assistant_node(state: ChatState) -> ChatState:
    """
    General assistant powered by the LLM.

    If a projectId is present in the state, it will:
      - fetch project documents
      - select the most relevant ones
      - pass them into the LLM as context for RAG-style answers
    """
    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        user_text = last[5:].strip()
    else:
        user_text = last

    project_id = state.get("projectId")

    # --- RAG: pull relevant project docs, if any ---
    top_docs = _get_top_project_docs(project_id, user_text, k=3)

    if top_docs:
        docs_block = "\n\n".join(
            f"[Document: {title}]\n{content}"
            for title, content in top_docs
        )
        prompt = (
            "You are a construction/project assistant. Use the project documents below "
            "if they are relevant to the user's question. If they are not relevant, "
            "answer from your own knowledge but do NOT invent project-specific facts.\n\n"
            f"{docs_block}\n\n"
            f"User question: {user_text}"
        )
    else:
        prompt = user_text

    response = llm.invoke(prompt)
    ai_reply = response.content

    return {
        "messages": state["messages"] + [f"ASSISTANT: {ai_reply}"],
        "projectId": project_id,
        "userId": state.get("userId"),
        "roleKey": state.get("roleKey"),
    }


# ---------- Project Info Node ----------

def project_info_node(state: ChatState) -> ChatState:
    """
    Returns a summary of the project based on projectId inside the state.
    Behavior varies by role:
      - PROJECT_MANAGER: full overview including members
      - Others: basic project info, limited team details
    """
    project_id_str = state.get("projectId")
    role_key = state.get("roleKey")

    if not project_id_str:
        reply = (
            "I can summarize the project, but no projectId was provided. "
            "Try asking again from inside an active project."
        )
        return {
            "messages": state["messages"] + [f"ASSISTANT: {reply}"],
            "projectId": project_id_str,
            "userId": state.get("userId"),
            "roleKey": role_key,
        }

    try:
        project_uuid = UUID(project_id_str)
    except (ValueError, TypeError):
        reply = (
            "I tried to look up this project, but the projectId format seems invalid. "
            "Please try again from an active project."
        )
        return {
            "messages": state["messages"] + [f"ASSISTANT: {reply}"],
            "projectId": project_id_str,
            "userId": state.get("userId"),
            "roleKey": role_key,
        }

    db: Session = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if not project:
            reply = (
                "I looked for that project in the database, but couldn't find it. "
                "It may have been deleted or you may not have access."
            )
            return {
                "messages": state["messages"] + [f"ASSISTANT: {reply}"],
                "projectId": project_id_str,
                "userId": state.get("userId"),
                "roleKey": role_key,
            }

        # Fetch members
        project_members = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == project_uuid)
            .all()
        )

        # Decide if this role can see full team details
        privileged_roles = {"PROJECT_MANAGER"}  # expand later as needed
        can_view_full_team = role_key in privileged_roles

        if can_view_full_team:
            member_lines = []
            for pm in project_members:
                role_name = pm.role.name if getattr(pm, "role", None) else "No role assigned"
                member_lines.append(f"- {role_name} (user id: {pm.user_id})")

            member_block = "\n".join(member_lines) if member_lines else "No members found."

            reply = (
                f"Project Overview (PM view):\n"
                f"Name: {project.name}\n"
                f"Description: {project.description or 'No description provided.'}\n"
                f"Status: {project.status}\n"
                f"Members:\n{member_block}"
            )
        else:
            # Non-PM roles get basic info only
            reply = (
                f"Project Overview:\n"
                f"Name: {project.name}\n"
                f"Description: {project.description or 'No description provided.'}\n"
                f"Status: {project.status}\n"
                "Team details are limited based on your role. "
                "Ask your Project Manager if you need more information."
            )
    finally:
        db.close()

    return {
        "messages": state["messages"] + [f"ASSISTANT: {reply}"],
        "projectId": project_id_str,
        "userId": state.get("userId"),
        "roleKey": role_key,
    }


def document_search_node(state: ChatState) -> ChatState:
    """
    RAG-lite node: search project documents and answer using their content.

    - Requires projectId in state
    - Searches title/content with a simple ILIKE text search
    - Feeds top matches into the LLM along with the user's question
    """
    project_id_str = state.get("projectId")
    role_key = state.get("roleKey")
    user_id = state.get("userId")

    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        query_text = last[5:].strip()
    else:
        query_text = last

    if not project_id_str:
        reply = (
            "I can search project documents, but no projectId was provided. "
            "Try asking again from inside an active project."
        )
        return {
            "messages": state["messages"] + [f"ASSISTANT: {reply}"],
            "projectId": project_id_str,
            "userId": user_id,
            "roleKey": role_key,
        }

    try:
        project_uuid = UUID(project_id_str)
    except (ValueError, TypeError):
        reply = (
            "I tried to look up this project's documents, but the projectId format "
            "seems invalid. Please try again from an active project."
        )
        return {
            "messages": state["messages"] + [f"ASSISTANT: {reply}"],
            "projectId": project_id_str,
            "userId": user_id,
            "roleKey": role_key,
        }

    db: Session = SessionLocal()
    try:
        # Basic text search against project documents
        q = (
            db.query(ProjectDocument)
            .filter(ProjectDocument.project_id == project_uuid)
            .filter(
                (ProjectDocument.title.ilike(f"%{query_text}%"))
                | (ProjectDocument.content.ilike(f"%{query_text}%"))
            )
            .order_by(ProjectDocument.created_at.desc())
            .limit(5)
        )

        docs = q.all()

        if not docs:
            reply = (
                "I searched the project documents but couldn't find anything clearly "
                "related to your question. Try rephrasing or adding more detail."
            )
            return {
                "messages": state["messages"] + [f"ASSISTANT: {reply}"],
                "projectId": project_id_str,
                "userId": user_id,
                "roleKey": role_key,
            }

        # Build a context string from the top documents
        context_chunks = []
        for idx, d in enumerate(docs, start=1):
            snippet = d.content[:600]  # first 600 chars
            context_chunks.append(
                f"Document {idx} - {d.title}:\n{snippet}\n"
            )

        context_text = "\n\n".join(context_chunks)

        prompt = (
            "You are an AI assistant helping with a construction project. "
            "Use ONLY the following project documents to answer the user's question. "
            "If the documents do not contain the answer, say you couldn't find "
            "anything definitive in the project documents.\n\n"
            f"User's question:\n{query_text}\n\n"
            f"Project documents:\n{context_text}\n\n"
            "Now provide a concise, helpful answer referencing the documents when appropriate."
        )

        response = llm.invoke(prompt)
        ai_reply = response.content

        return {
            "messages": state["messages"] + [f"ASSISTANT: {ai_reply}"],
            "projectId": project_id_str,
            "userId": user_id,
            "roleKey": role_key,
        }

    finally:
        db.close()


# ---------- Router Node + Routing Logic ----------

def router_identity(state: ChatState) -> ChatState:
    """
    Router node doesn't change state; it just exists so we can attach
    conditional edges based on the latest user message.
    """
    return state


def route_from_text(state: ChatState) -> str:
    """
    Decide where to send the next step based on the latest user message.

    Returns:
        "project_info" -> project_info_node
        "board_foot"   -> board_foot_node
        "sheet"        -> sheet_count_node
        "cost"         -> material_cost_node
        "measure"      -> construction_measurement_node
        "doc_search"   -> document_search_node
        "chat"         -> assistant_node
    """
    last = state["messages"][-1]
    if last.lower().startswith("user:"):
        text = last[5:].strip().lower()
    else:
        text = last.lower()

    # Project-related questions
    project_keywords = [
        "project overview",
        "project summary",
        "about this project",
        "what is this project",
        "project info",
        "team",
        "members",
        "who is on this project",
        "who is on the team",
    ]
    if any(k in text for k in project_keywords):
        return "project_info"

    # Document / specs questions
    doc_keywords = [
        "spec",
        "specs",
        "specification",
        "document",
        "documents",
        "docs",
        "plans",
        "blueprint",
        "rfis",
        "rfi",
        "change order",
        "submittal",
    ]
    if any(k in text for k in doc_keywords):
        return "doc_search"

    # Cost-focused queries
    cost_keywords = [
        "cost",
        "price",
        "total",
        "material",
        "per sheet",
        "per board",
        "per bf",
        "$",
    ]
    if any(k in text for k in cost_keywords):
        return "cost"

    # Explicit board-foot requests
    board_foot_keywords = [
        "board foot",
        "board feet",
        "bf",
    ]
    if any(k in text for k in board_foot_keywords):
        return "board_foot"

    # Sheet-related requests
    sheet_keywords = [
        "sheet",
        "sheets",
        "drywall",
        "plywood",
        "osb",
        "panel",
        "panels",
        "sq ft",
        "sqft",
        "square feet",
        "sf",
    ]
    if any(k in text for k in sheet_keywords):
        return "sheet"

    # Measurement (length) requests
    measurement_keywords = [
        "ft", "feet", "foot",
        "in", "inch", "inches",
        "'", "\"",
        "measurement",
        "convert",
        "stud",
        "2x4",
        "framing",
    ]
    if any(k in text for k in measurement_keywords):
        return "measure"

    return "chat"


def build_graph():
    """
    Build and compile the LangGraph app.
    """
    graph = StateGraph(ChatState)

    # Nodes
    graph.add_node("router", router_identity)
    graph.add_node("assistant", assistant_node)
    graph.add_node("construction_measurement", construction_measurement_node)
    graph.add_node("board_foot", board_foot_node)
    graph.add_node("sheet", sheet_count_node)
    graph.add_node("cost", material_cost_node)
    graph.add_node("project_info", project_info_node)
    graph.add_node("doc_search", document_search_node)

    # Entry point
    graph.set_entry_point("router")

    # Conditional routing based on user text
    graph.add_conditional_edges(
        "router",
        route_from_text,
        {
            "project_info": "project_info",
            "doc_search": "doc_search",
            "board_foot": "board_foot",
            "sheet": "sheet",
            "cost": "cost",
            "measure": "construction_measurement",
            "chat": "assistant",
        },
    )

    # Terminal edges
    graph.add_edge("project_info", END)
    graph.add_edge("doc_search", END)
    graph.add_edge("board_foot", END)
    graph.add_edge("sheet", END)
    graph.add_edge("cost", END)
    graph.add_edge("construction_measurement", END)
    graph.add_edge("assistant", END)

    return graph.compile()


# Compile once so main.py can import app_graph
app_graph = build_graph()
