import base64
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
load_dotenv(BASE_DIR / ".env")

MAX_IMAGE_SIZE = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_FORMAT_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "inclusionai/ling-3.2-flash:free")

app = FastAPI(title="Leafwise Plant Health")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class PlantAnalysis(BaseModel):
    plant_name: str = Field(description="Likely plant name, or Unknown")
    condition: str = Field(description="Brief description of visible plant condition")
    disease: str = Field(description="Likely disease, or No clear disease visible")
    symptoms: list[str] = Field(description="Visible symptoms observed in the photo")
    treatment: list[str] = Field(description="Practical next steps for the grower")
    prevention: list[str] = Field(description="Ways to prevent this condition from spreading or returning")
    estimated_days_to_severe_decline: int | None = Field(
        ge=1,
        le=3650,
        description="A rough estimate only when severe decline is visually supported; otherwise null",
    )
    survival_outlook: str = Field(
        description="Cautious explanation of prognosis and uncertainty based on this single photo"
    )
    confidence: int = Field(ge=0, le=100, description="Confidence from 0 to 100")


class PlantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1200)


class PlantAnswer(BaseModel):
    answer: str


PLANT_ANALYSIS_PROMPT = (
    "You are a cautious crop-health assistant. Inspect this plant photo and return "
    "one JSON object with exactly these keys: plant_name (string), condition (string), "
    "disease (string), symptoms (array of strings), treatment (array of strings), "
    "prevention (array of strings), estimated_days_to_severe_decline (integer or null), "
    "survival_outlook (string), confidence (integer from 0 to 100). Identify the plant "
    "and likely disease only when visible evidence supports it. Describe visible "
    "symptoms, practical low-risk treatment, and prevention. A single photo cannot "
    "reliably predict when a plant will die: set estimated_days_to_severe_decline to "
    "null unless visible evidence supports a cautious rough timeframe for severe "
    "decline; never invent an exact death date or imply certainty. In survival_outlook, "
    "explain uncertainty and recommend what to monitor. If no disease is clear, say so "
    "and suggest what to inspect next. Never recommend hazardous chemical use."
)


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, bool | str]:
    if AI_PROVIDER == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
    elif AI_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
    else:
        api_key = None
    configured = bool(api_key and api_key.strip() and "paste_your_" not in api_key.lower())
    return {"ai_configured": configured, "ai_provider": AI_PROVIDER}


PLANT_CHAT_PROMPT = (
    "You are Leafwise, a careful and practical plant-care assistant. Answer the user's "
    "question about plant identification, growing conditions, watering, light, soil, "
    "pests, diseases, and treatments. Be specific and explain uncertainty when the "
    "plant or symptoms are unclear. Prefer low-risk, practical steps and integrated "
    "pest management. Do not invent certainty, recommend mixing chemicals, or give "
    "unsafe pesticide directions. For serious crop loss, advise consulting a local "
    "agricultural extension expert. Keep the answer readable with short paragraphs "
    "or bullets."
)


async def answer_with_ai(question: str) -> str:
    if AI_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="Add GEMINI_API_KEY to .env and restart the app.")
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
        payload = {"contents": [{"parts": [{"text": f"{PLANT_CHAT_PROMPT}\n\nUser question: {question}"}]}]}
        headers = {"x-goog-api-key": api_key}
        provider = "Gemini"
    elif AI_PROVIDER == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="Add OPENROUTER_API_KEY to .env and restart the app.")
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": PLANT_CHAT_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": 0.4,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        provider = "OpenRouter"
    else:
        raise HTTPException(status_code=503, detail="Set AI_PROVIDER to 'gemini' or 'openrouter' in .env.")

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            answer = (
                result["candidates"][0]["content"]["parts"][0]["text"]
                if AI_PROVIDER == "gemini"
                else result["choices"][0]["message"]["content"]
            )
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Empty answer")
            return answer.strip()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(status_code=503, detail=f"{provider} request limit reached. Please try again later.") from exc
        if exc.response.status_code in {401, 403}:
            raise HTTPException(status_code=503, detail=f"{provider} did not accept the API key. Check your .env configuration.") from exc
        raise HTTPException(status_code=502, detail=f"{provider} could not answer right now. Please try again.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"{provider} took too long to respond. Please try again.") from exc
    except (httpx.RequestError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The AI returned an unusable answer. Please try again.") from exc


@app.post("/api/ask", response_model=PlantAnswer)
async def ask_plant_question(request: PlantQuestion) -> PlantAnswer:
    return PlantAnswer(answer=await answer_with_ai(request.question.strip()))


async def analyze_with_gemini(image_bytes: bytes, mime_type: str) -> PlantAnalysis:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI is not configured yet. Add GEMINI_API_KEY to your environment and restart the app.",
        )

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PLANT_ANALYSIS_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                endpoint,
                headers={"x-goog-api-key": api_key},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            response_text = result["candidates"][0]["content"]["parts"][0]["text"]
            return PlantAnalysis.model_validate(json.loads(response_text))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="Gemini is temporarily busy. Please try again in a minute.",
            ) from exc
        if exc.response.status_code == 429:
            raise HTTPException(
                status_code=503,
                detail="Gemini's request limit has been reached. Please try again later or check your AI Studio quota.",
            ) from exc
        if exc.response.status_code in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail="Gemini did not accept the API key. Check that it is active and enabled for the Gemini API.",
            ) from exc
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail="The configured Gemini model is unavailable. Check the model setting and try again later.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Gemini could not analyze this image. Please try again later.",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Gemini took too long to respond. Please try again.",
        ) from exc
    except (
        httpx.RequestError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail="The AI provider returned an unusable result. Please try another clear photo.",
        ) from exc


async def analyze_with_openrouter(image_bytes: bytes, mime_type: str) -> PlantAnalysis:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter is not configured. Add OPENROUTER_API_KEY to your .env file and restart the app.",
        )

    image_data = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PLANT_ANALYSIS_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                    },
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            response_text = result["choices"][0]["message"]["content"]
            return PlantAnalysis.model_validate(json.loads(response_text))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise HTTPException(
                status_code=503,
                detail="The free AI model is at its request limit. Please try again later.",
            ) from exc
        if exc.response.status_code in {401, 403}:
            raise HTTPException(
                status_code=503,
                detail="OpenRouter did not accept the API key. Check that it is active.",
            ) from exc
        if exc.response.status_code == 402:
            raise HTTPException(
                status_code=503,
                detail="OpenRouter could not use the free model for this request. Check your account and selected model.",
            ) from exc
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=503,
                detail="The configured free model is unavailable. Check OPENROUTER_MODEL and try again later.",
            ) from exc
        if exc.response.status_code in {502, 503}:
            raise HTTPException(
                status_code=503,
                detail="The free AI model is temporarily busy. Please try again in a minute.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="OpenRouter could not analyze this image. Please try again later.",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="The free AI model took too long to respond. Please try again.",
        ) from exc
    except (
        httpx.RequestError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        ValidationError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail="The AI provider returned an unusable result. Please try another clear photo.",
        ) from exc


@app.post("/api/analyze", response_model=PlantAnalysis)
async def analyze_plant(
    photo: Annotated[UploadFile, File(description="A JPEG, PNG, or WebP plant photo")],
) -> PlantAnalysis:
    if photo.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Please upload a JPEG, PNG, or WebP image.",
        )

    image_bytes = await photo.read(MAX_IMAGE_SIZE + 1)
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Image must be 8 MB or smaller.")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The selected image is empty.")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            actual_content_type = IMAGE_FORMAT_MIME_TYPES.get(image.format)
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="That file is not a readable image. Please choose another photo.",
        ) from exc

    if width < 64 or height < 64:
        raise HTTPException(
            status_code=400,
            detail="Please use an image at least 64 by 64 pixels.",
        )
    if width * height > 25_000_000:
        raise HTTPException(
            status_code=413,
            detail="That image has too many pixels. Please use a smaller photo.",
        )
    if actual_content_type != photo.content_type:
        raise HTTPException(
            status_code=400,
            detail="The image content does not match its file type. Please choose another photo.",
        )

    if AI_PROVIDER == "openrouter":
        return await analyze_with_openrouter(image_bytes, photo.content_type)
    if AI_PROVIDER == "gemini":
        return await analyze_with_gemini(image_bytes, photo.content_type)
    raise HTTPException(
        status_code=503,
        detail="Unsupported AI_PROVIDER. Set it to 'openrouter' or 'gemini' in your .env file.",
    )
