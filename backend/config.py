from settings import settings

KUMO_API_KEY = settings.kumo_api_key
HOST = settings.host
PORT = settings.port

if not KUMO_API_KEY:
    print("WARNING: KUMO_API_KEY not set. Set it in .env file or environment.")
