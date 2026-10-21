"""Small client used by the gateway to call the private AWS Lambda transcription function."""
import base64
import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def lambda_client():
    """Create and cache one Lambda client so repeated microphone requests are faster."""
    import boto3
    from botocore.config import Config
    # Timeouts stop a temporary AWS problem from making the browser wait forever.
    return boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "ap-south-1"),
                        config=Config(connect_timeout=3, read_timeout=65,
                                      retries={"mode": "standard", "total_max_attempts": 1}))


def invoke_transcription(audio):
    """Base64-encode short audio, invoke Lambda synchronously, and validate its reply."""
    # RequestResponse means the gateway waits for the text result; it is not an asynchronous background job.
    response = lambda_client().invoke(
        FunctionName=os.environ["TRANSCRIBE_LAMBDA_FUNCTION"],
        InvocationType="RequestResponse",
        # Base64 changes binary audio into JSON-safe text for the Lambda event.
        Payload=json.dumps({"audio_base64": base64.b64encode(audio).decode("ascii")}).encode(),
    )
    # AWS returns a streaming payload object, so read it before decoding the JSON result.
    with response["Payload"] as stream:
        result = json.loads(stream.read())
    # Convert Lambda/provider errors into normal Python errors for the gateway to handle safely.
    if response.get("FunctionError"):
        raise RuntimeError("Lambda transcription failed")
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise ValueError("Invalid transcription response")
    return {"text": result["text"], "stt_source": result.get("stt_source", "error")}
