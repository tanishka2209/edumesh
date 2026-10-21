"""EduMesh gateway: serves the website and forwards each request to the right subject service."""

import os
import random
import time
import requests
import concurrent.futures
from fastapi import FastAPI, UploadFile, File, HTTPException
from lambda_transcribe import MAX_AUDIO_BYTES
from transcription_client import invoke_transcription
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Local development reads keys/settings from .env. AWS gets its settings from Kubernetes instead.
load_dotenv()

# This is the single public API that the browser talks to.
app = FastAPI(title="EduMesh Gateway")

@app.get("/live")
def live():
    """Probe this process without depending on subject-service availability."""
    return {"status": "up"}

@app.get("/", response_class=FileResponse)
def read_index():
    """Return the web page and prevent browsers from using an old cached version."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(
        os.path.join(current_dir, "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A subject must score at least 30/100 before it is allowed to answer the question.
CONFIDENCE_THRESHOLD = 30

# One stable address for each microservice. Docker/Kubernetes replaces these values using environment variables.
SERVICES = {
    "ML": {
        "url": os.environ.get("ML_URL", "http://127.0.0.1:5001"),
        "display_name": "Machine Learning"
    },
    "DBMS": {
        "url": os.environ.get("DBMS_URL", "http://127.0.0.1:5002"),
        "display_name": "Database Management Systems"
    },
    "CLOUD": {
        "url": os.environ.get("CLOUD_URL", "http://127.0.0.1:5003"),
        "display_name": "Cloud Computing"
    }
}

class AskBidsRequest(BaseModel):
    """Data the browser sends when it asks all subjects to score a question."""
    question: str

class AskAnswerRequest(BaseModel):
    """Data needed to ask the subject service that won the bidding round."""
    query_id: str
    question: str
    winner: str
    matched_topic: str

def call_bid(service_id: str, service_url: str, default_display: str, query_id: str, question: str):
    """Utility to call POST /can_handle on a subject service with 2-second timeout."""
    # /can_handle only checks keywords; it does not call the AI, so it should be fast.
    url = f"{service_url.rstrip('/')}/can_handle"
    headers = {"Content-Type": "application/json"}
    payload = {"query_id": query_id, "question": question}
    
    print(f"[Gateway] [query_id={query_id}] Sending POST {url} to {service_id}")
    start_time = time.perf_counter()
    try:
        # Two seconds prevents one broken subject service from delaying every user question.
        response = requests.post(url, json=payload, headers=headers, timeout=2.0)
        latency = int((time.perf_counter() - start_time) * 1000)
        if response.status_code == 200:
            res_json = response.json()
            print(f"[Gateway] [query_id={query_id}] Received response from {service_id} in {latency}ms: score={res_json.get('score')}")
            return {
                "service": service_id,
                "display_name": res_json.get("display_name", default_display),
                "score": res_json.get("score", 0),
                "matched": res_json.get("matched", {"tier1": [], "tier2": [], "tier3": []}),
                "status": "ok",
                "latency_ms": latency
            }
        else:
            print(f"[Gateway] [query_id={query_id}] {service_id} returned non-200 status code {response.status_code}")
    except Exception as e:
        print(f"[Gateway] [query_id={query_id}] Exception while calling {service_id}: {e}")
        
    # Return a safe zero-score bid if this service is unavailable; other subjects can still win.
    return {
        "service": service_id,
        "display_name": default_display,
        "score": 0,
        "matched": {"tier1": [], "tier2": [], "tier3": []},
        "status": "unavailable",
        "latency_ms": None
    }

@app.post("/ask/bids")
def ask_bids(payload: AskBidsRequest):
    """Ask ML, DBMS, and Cloud in parallel, then choose the highest confident score."""
    # A short ID connects all logs from this one user question.
    query_id = f"q-{random.randint(1000, 9999)}"
    print(f"[Gateway] [query_id={query_id}] Received POST /ask/bids for question: '{payload.question}'")
    
    # Each subject returns its own score and the keywords it recognized.
    bids = []
    # Query all three service instances concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                call_bid, 
                sid, 
                sinfo["url"], 
                sinfo["display_name"], 
                query_id, 
                payload.question
            ): sid for sid, sinfo in SERVICES.items()
        }
        for future in concurrent.futures.as_completed(futures):
            bids.append(future.result())
            
    # Sort bids: score DESC, then len(tier1) DESC, then total matched terms DESC, then service id ASCENDING
    def sort_key(bid):
        """Make ties predictable: prefer more important and more total matched keywords."""
        score = bid.get("score", 0)
        matched = bid.get("matched", {})
        t1 = matched.get("tier1", [])
        t2 = matched.get("tier2", [])
        t3 = matched.get("tier3", [])
        total_matched = len(t1) + len(t2) + len(t3)
        service_id = bid.get("service", "")
        return (-score, -len(t1), -total_matched, service_id)
        
    # Sorting makes the selection repeatable even if two subjects have a similar score.
    bids.sort(key=sort_key)
    
    winner = None
    confident = False
    
    # Only select a winner when it passes the minimum confidence rule.
    if bids:
        top_bid = bids[0]
        if top_bid["score"] >= CONFIDENCE_THRESHOLD:
            winner = top_bid["service"]
            confident = True
            
    response_data = {
        "query_id": query_id,
        "question": payload.question,
        "bids": bids,
        "winner": winner,
        "threshold": CONFIDENCE_THRESHOLD,
        "confident": confident
    }
    print(f"[Gateway] [query_id={query_id}] Responding to /ask/bids: winner={winner}, confident={confident}")
    return response_data

@app.post("/ask/answer")
def ask_answer(payload: AskAnswerRequest):
    """Forward a normal, non-streaming answer request to the selected subject."""
    query_id = payload.query_id
    winner = payload.winner
    print(f"[Gateway] [query_id={query_id}] Received POST /ask/answer for winner: {winner}")
    
    if winner not in SERVICES:
        print(f"[Gateway] [query_id={query_id}] Winner '{winner}' is not configured.")
        return {
            "query_id": query_id,
            "service": winner,
            "display_name": winner,
            "answer": f"Error: Winner '{winner}' is not a valid service in Gateway configuration.",
            "answer_source": "error",
            "cached": False,
            "latency_ms": 0
        }
        
    # Build the private URL for only the subject that won the bidding stage.
    service_info = SERVICES[winner]
    url = f"{service_info['url'].rstrip('/')}/answer"
    headers = {"Content-Type": "application/json"}
    sub_payload = {
        "query_id": query_id,
        "question": payload.question,
        "matched_topic": payload.matched_topic
    }
    
    print(f"[Gateway] [query_id={query_id}] Forwarding answer request to {winner} at {url}")
    start_time = time.perf_counter()
    try:
        # AI answers can take longer than keyword bidding, so this path has a longer timeout.
        response = requests.post(url, json=sub_payload, headers=headers, timeout=30.0)
        latency = int((time.perf_counter() - start_time) * 1000)
        if response.status_code == 200:
            res_json = response.json()
            print(f"[Gateway] [query_id={query_id}] Received answer response from {winner} in {latency}ms")
            return {
                "query_id": query_id,
                "service": winner,
                "display_name": res_json.get("display_name", service_info["display_name"]),
                "answer": res_json.get("answer", ""),
                "answer_source": res_json.get("answer_source", "error"),
                "cached": res_json.get("cached", False),
                "latency_ms": latency
            }
        else:
            print(f"[Gateway] [query_id={query_id}] {winner} answered with non-200 HTTP code {response.status_code}")
            return {
                "query_id": query_id,
                "service": winner,
                "display_name": service_info["display_name"],
                "answer": f"Error: Service {winner} returned status code {response.status_code}.",
                "answer_source": "error",
                "cached": False,
                "latency_ms": int((time.perf_counter() - start_time) * 1000)
            }
    except Exception as e:
        latency = int((time.perf_counter() - start_time) * 1000)
        print(f"[Gateway] [query_id={query_id}] Exception forwarding answer request to {winner}: {e}")
        return {
            "query_id": query_id,
            "service": winner,
            "display_name": service_info["display_name"],
            "answer": f"Error: Failed to contact service {winner}. Details: {str(e)}",
            "answer_source": "error",
            "cached": False,
            "latency_ms": latency
        }

@app.get("/health")
def health():
    """Return one health result for every subject service so monitoring can find failures."""
    print("[Gateway] Received GET /health, query all backend services...")
    # The result is a small dashboard: one status entry for each subject.
    results = {}
    
    def check_health(sid: str, url: str):
        """Check one subject quickly; a failed service must not break the whole health check."""
        target = f"{url.rstrip('/')}/health"
        try:
            res = requests.get(target, timeout=2.0)
            if res.status_code == 200:
                return sid, res.json()
        except Exception:
            pass
        return sid, {"status": "unavailable"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(check_health, sid, sinfo["url"])
            for sid, sinfo in SERVICES.items()
        ]
        for future in concurrent.futures.as_completed(futures):
            sid, status = future.result()
            results[sid] = status
            
    print(f"[Gateway] Aggregate health statuses: {results}")
    return results

@app.post("/ask/transcribe")
def ask_transcribe(file: UploadFile = File(...)):
    """Validate recorded audio, then prefer Lambda or fall back to the ML service."""
    # Read one extra byte so we can reliably reject a file above the 4 MiB safety limit.
    audio = file.file.read(MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Audio recording is empty")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Record a shorter clip (maximum 4 MiB)")
    # Production uses Lambda. Local Docker can use the ML-service fallback without AWS access.
    if os.environ.get("TRANSCRIBE_LAMBDA_FUNCTION"):
        try:
            return invoke_transcription(audio)
        except Exception:
            print("[Gateway] Lambda transcription unavailable")
            return {"text": "", "stt_source": "error"}
    print("[Gateway] Forwarding audio file to ML Service for transcription...")
    url = f"{SERVICES['ML']['url'].rstrip('/')}/transcribe_audio"
    try:
        file.file.seek(0)
        files = {"file": (file.filename or "audio.webm", file.file, file.content_type or "audio/webm")}
        res = requests.post(url, files=files, timeout=60)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Gateway] Error proxying transcribe request: {e}")
    return {"text": "", "stt_source": "error"}

@app.post("/ask/answer_stream")
def ask_answer_stream(payload: AskAnswerRequest):
    """Pass AI tokens through as they arrive, so the browser can show a live answer."""
    query_id = payload.query_id
    winner = payload.winner
    print(f"[Gateway] [query_id={query_id}] Proxying answer_stream to {winner}")
    
    if winner not in SERVICES:
        def err_gen():
            """Create a one-message stream when the requested subject does not exist."""
            yield f"Error: Winner '{winner}' is not configured."
        return StreamingResponse(err_gen(), media_type="text/plain")

    # The gateway does not generate the answer itself; it only forwards the stream from the winner.
    service_info = SERVICES[winner]
    url = f"{service_info['url'].rstrip('/')}/answer_stream"
    sub_payload = {
        "query_id": query_id,
        "question": payload.question,
        "matched_topic": payload.matched_topic
    }
    
    def proxy_chunks():
        """Copy small chunks from the subject service without waiting for the full answer."""
        try:
            # stream=True lets us forward pieces of text immediately instead of storing a full answer first.
            with requests.post(url, json=sub_payload, stream=True, timeout=30) as resp:
                for chunk in resp.iter_content(chunk_size=1024):
                    if chunk:
                        yield chunk
        except Exception as e:
            print(f"[Gateway] [query_id={query_id}] Streaming proxy exception: {e}")
            yield f"Error: Failed to stream from service {winner}."

    return StreamingResponse(proxy_chunks(), media_type="text/plain")
