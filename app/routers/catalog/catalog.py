import httpx
from fastapi import APIRouter, Depends, HTTPException
import time
import jwt

from app.core.config import settings
from app.core.dependencies import get_http_client

router = APIRouter()



def generate_jwt_token():
    """
    Using the secret key and api-key we need to generate token.
    """
    token_creation_time = int(time.time())
    payload = {
        "iss": settings.PI_KEY,
        "iat": token_creation_time
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    return token


@router.get("/")
async def get_catalog(
        channel: str,
        http_client: httpx.AsyncClient = Depends(get_http_client)
):
    headers = {
        "x-api-key": settings.PI_KEY,
        "x-api-token": generate_jwt_token(),
        "content-type": 'application/json'
    }
    params = {
        "branch": settings.BRANCH_CODE,
        "channel": channel
    }

    try:
        url = f"{settings.RISTA_BASE_URL}/catalog"
        response = await http_client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        # Handle errors from the KDS API
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from KDS API: {e.response.text}")
    except httpx.RequestError as e:
        # Handle network errors
        raise HTTPException(status_code=502, detail=f"Cannot connect to KDS API: {str(e)}")