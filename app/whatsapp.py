import os
from urllib.parse import urlparse

import httpx
from twilio.rest import Client

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
FROM_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def download_media(media_url):
    if urlparse(media_url).hostname != "api.twilio.com":
        raise ValueError("Media URL is not on api.twilio.com")
    response = httpx.get(
        media_url, auth=(ACCOUNT_SID, AUTH_TOKEN), follow_redirects=True, timeout=30
    )
    response.raise_for_status()
    return response.content


def send_whatsapp_message(to_number, body):
    client.messages.create(from_=FROM_NUMBER, to=to_number, body=body)
