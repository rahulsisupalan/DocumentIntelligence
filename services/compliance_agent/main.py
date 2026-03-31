"""
Compliance Agent Service
=========================
This is the THIRD STEP in the pipeline (for high-confidence documents).

What it does:
  1. Receives a document payload from the Worker (via Pub/Sub).
  2. Runs an automated LangGraph "agent" to audit the extracted data against company rules.
     - Node 1 (Setup Rules): Figures out which rules to check based on the document type.
     - Node 2 (Evaluate Rules): Uses an LLM to check if each rule is satisfied.
  3. Adds the compliance results to the payload and forwards to the Storage Router.

Why LangGraph?
  LangGraph lets us define the audit as a series of connected steps (a state machine),
  making it easy to add more audit steps (e.g., fraud detection, legal review) in the future.
"""

import base64
import json
import os
import logging
from typing import TypedDict, List
from fastapi import FastAPI, Request, HTTPException
from google.cloud import pubsub_v1
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

# ── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App Initialization ───────────────────────────────────────────────────────
app = FastAPI(title="Compliance Agent Service")

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID    = os.getenv("PROJECT_ID",    "your-project-id")
LOCATION      = os.getenv("LOCATION",      "us-central1")
STORAGE_TOPIC = os.getenv("STORAGE_TOPIC", "route-to-storage")

# ── GCP Client Setup ─────────────────────────────────────────────────────────
publisher = pubsub_v1.PublisherClient()

# Gemini Pro is used here because checking rules requires careful, nuanced reasoning.
llm = ChatVertexAI(model_name="gemini-1.5-pro-001", project=PROJECT_ID, location=LOCATION)


# ── LangGraph Agent Definition ───────────────────────────────────────────────────

# AgentState is a simple dictionary that flows through each step of the agent.
# Each node (step) reads values from this state and writes new values back to it.
class AgentState(TypedDict):
    document_type:    str         # e.g. "INVOICE", "CONTRACT"
    extracted_data:   dict        # The fields extracted from the document
    rules_to_check:   List[str]   # Rules populated by node_setup_rules
    compliance_report: List[dict] # Results filled in by node_evaluate_rules
    is_compliant:     bool        # Final answer: did the document pass all rules?


def node_setup_rules(state: AgentState) -> AgentState:
    """
    Agent Node 1: Determine which compliance rules apply based on document type.
    In a real system, these rules would be fetched from a Vector Database
    using the document type as a search query.
    """
    logger.info("Agent Step 1: Loading compliance rules for document type: %s", state["document_type"])
    doc_type = state["document_type"]

    if doc_type == "INVOICE":
        rules = [
            "Rule 1: Invoice must have a Vendor Name.",
            "Rule 2: Total Amount must be greater than 0.",
            "Rule 3: Must include a valid Date."
        ]
    elif doc_type == "CONTRACT":
        rules = [
            "Rule 1: Contract Type must be clearly stated.",
            "Rule 2: Signatures must be present."
        ]
    else:
        rules = ["Rule 1: Document must not be blank."]

    return {"rules_to_check": rules, "compliance_report": [], "is_compliant": True}


def node_evaluate_rules(state: AgentState) -> AgentState:
    """
    Agent Node 2: Check each rule against the extracted data using the LLM.
    The LLM acts as an intelligent compliance officer that understands nuance.
    """
    logger.info("Agent Step 2: Evaluating %d rules against document data.", len(state["rules_to_check"]))
    report = []

    for rule in state["rules_to_check"]:
        # Ask the LLM: "Does this data satisfy this rule? Answer in JSON."
        prompt = f"""
        You are a compliance officer reviewing a document.
        Rule to check: {rule}
        Document Data: {json.dumps(state['extracted_data'])}

        Does the document data satisfy this rule? Respond ONLY with valid JSON:
        {{"passed": true or false, "reason": "brief explanation"}}
        """
        try:
            response   = llm.invoke([HumanMessage(content=prompt)])
            clean_json = response.content.replace('```json', '').replace('```', '').strip()
            result     = json.loads(clean_json)
        except Exception as e:
            logger.error("Failed to evaluate rule '%s': %s", rule, e)
            result = {"passed": False, "reason": "Error occurred during rule evaluation."}

        report.append({"rule": rule, "result": result})

    # The document is only compliant if ALL rules passed.
    all_passed = all(item["result"].get("passed", False) for item in report)
    return {"compliance_report": report, "is_compliant": all_passed}


# ── Build and Compile the LangGraph Agent ──────────────────────────────────────────
# This creates a simple 2-step graph: Setup Rules -> Evaluate Rules -> Done
workflow = StateGraph(AgentState)
workflow.add_node("setup_rules",    node_setup_rules)
workflow.add_node("evaluate_rules", node_evaluate_rules)
workflow.set_entry_point("setup_rules")
workflow.add_edge("setup_rules",    "evaluate_rules")
workflow.add_edge("evaluate_rules", END)
compliance_agent = workflow.compile()


# ── Helper Functions ─────────────────────────────────────────────────────────

def publish_to_topic(topic_id: str, payload: dict):
    """Sends a JSON payload to a Google Cloud Pub/Sub topic."""
    if PROJECT_ID == "your-project-id":
        logger.warning(f"[DRY RUN] Would publish to '{topic_id}'.")
        return
    topic_path = publisher.topic_path(PROJECT_ID, topic_id)
    future = publisher.publish(topic_path, json.dumps(payload).encode("utf-8"))
    future.result()


# ── Main API Endpoint ─────────────────────────────────────────────────────────

@app.post("/")
async def handle_compliance_audit(request: Request):
    """
    This endpoint is called by Pub/Sub with a high-confidence document payload.
    It runs the 2-step LangGraph compliance agent and forwards the results.
    """
    # ── Step 1: Decode the Pub/Sub Message ───────────────────────────────────
    envelope = await request.json()
    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid or empty Pub/Sub message.")

    raw_data = base64.b64decode(envelope["message"]["data"]).decode("utf-8")
    payload  = json.loads(raw_data)
    logger.info("Starting Compliance Audit for: %s", payload.get("gcs_uri"))

    # ── Step 2: Run the Compliance Agent ────────────────────────────────────
    # Prepare the initial state for the LangGraph agent
    initial_state = {
        "document_type":   payload.get("document_type"),
        "extracted_data":  payload.get("extracted_data"),
        "rules_to_check":  [],
        "compliance_report": [],
        "is_compliant":    False,
    }
    final_state = compliance_agent.invoke(initial_state)
    logger.info("Compliance Audit complete. Document is compliant: %s", final_state["is_compliant"])

    # ── Step 3: Forward to Storage Router ────────────────────────────────────
    # Attach the compliance results to the original payload
    payload["compliance_report"] = final_state["compliance_report"]
    payload["is_compliant"]      = final_state["is_compliant"]

    # Send the fully enriched payload to the Storage Router
    publish_to_topic(STORAGE_TOPIC, payload)

    return {"status": "success", "is_compliant": final_state["is_compliant"]}
