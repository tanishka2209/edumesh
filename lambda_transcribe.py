"""Private Lambda handler: safely turns one short browser audio clip into text."""
import base64
import binascii
import os
from functools import lru_cache

import requests

# Hard safety limit: Lambda only receives short recordings, so costs and memory stay controlled.
MAX_AUDIO_BYTES = 4 * 1024 * 1024

@lru_cache(maxsize=1)
def provider_keys():
    """Read API keys from local environment variables or AWS Parameter Store, then cache them."""
    # Local development can use .env. AWS production normally leaves these empty and uses Parameter Store.
    groq_key = os.environ.get("GROQ_API_KEY")
    deepgram_key = os.environ.get("DEEPGRAM_API_KEY")
    # Only request parameters whose names were configured; no secret values are printed in logs.
    parameter_names = [name for name in (
        os.environ.get("GROQ_API_KEY_PARAMETER"),
        os.environ.get("DEEPGRAM_API_KEY_PARAMETER"),
    ) if name]
    # Contact AWS only when a required key is not already available locally.
    if parameter_names and (not groq_key or not deepgram_key):
        import boto3
        parameters = boto3.client(
            "ssm", region_name=os.environ.get("AWS_REGION", "ap-south-1")
        ).get_parameters(
            Names=parameter_names, WithDecryption=True
        )["Parameters"]
        # Make a simple name-to-value lookup from AWS's list response.
        values = {item["Name"]: item["Value"] for item in parameters}
        groq_key = groq_key or values.get(os.environ.get("GROQ_API_KEY_PARAMETER"))
        deepgram_key = deepgram_key or values.get(os.environ.get("DEEPGRAM_API_KEY_PARAMETER"))
    return groq_key, deepgram_key


def transcribe(audio, filename="audio.webm", content_type="audio/webm"):
    """Shared by the local subject service and Lambda; never persists audio."""
    groq_key, deepgram_key = provider_keys()
    # Groq Whisper is the first choice for transcription.
    if groq_key:
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files={"file": (filename, audio, content_type)},
                data={"model": "whisper-large-v3"}, timeout=(3, 15),
            )
            response.raise_for_status()
            return {"text": response.json()["text"], "stt_source": "groq_whisper"}
        except (requests.RequestException, ValueError, KeyError):
            print("Groq transcription failed; trying Deepgram")
    # Deepgram is a backup, so a Groq outage does not automatically break the microphone feature.
    if deepgram_key:
        try:
            response = requests.post(
                "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true",
                headers={"Authorization": f"Token {deepgram_key}", "Content-Type": content_type},
                data=audio, timeout=(3, 15),
            )
            response.raise_for_status()
            text = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
            return {"text": text, "stt_source": "deepgram"}
        except (requests.RequestException, ValueError, KeyError, IndexError):
            print("Deepgram transcription failed")
    return {"text": "", "stt_source": "error"}


def handler(event, context):
    """Lambda entry point: validate base64 audio before sending it to a transcription provider."""
    # Lambda JSON events cannot carry raw binary safely, so the gateway sends base64 text.
    encoded = event.get("audio_base64", "")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_AUDIO_BYTES + 2) // 3):
        raise ValueError("Invalid or oversized audio")
    # validate=True rejects invalid characters instead of silently accepting damaged input.
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid base64 audio") from error
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("Audio must be between 1 byte and 4 MiB")
    return transcribe(audio)
