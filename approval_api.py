from fastapi import FastAPI, HTTPException
from governance.persistence.approval_repository import list_pending_approvals

app = FastAPI(title="AGT Approval API", docs_url=None, redoc_url=None)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/approvals/pending")
def pending():
    return {"approvals": [
        {
            "request_id": item["id"],
            "tool_name": item.get("tool_name"),
            "arguments": item.get("arguments"),
            "reason": item.get("reason"),
            "status": item["status"],
        }
        for item in list_pending_approvals()
    ]}

@app.post("/approvals/{request_id}/decision")
def decision(request_id: str):
    raise HTTPException(status_code=503, detail="Reviewer authentication not configured")
