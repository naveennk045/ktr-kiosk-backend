import time
import jwt
from .config import settings
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
