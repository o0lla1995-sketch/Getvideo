from fastapi import FastAPI, Query
import requests
import re

app = FastAPI()

@app.get("/extract-url")
async def extract_url(url: str = Query(...)):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.xvideos.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            match = re.search(r"setVideoUrlHigh\('(.*?)'\)", response.text)
            if match:
                return {"success": True, "streamUrl": match.group(1)}
        return {"success": False, "error": "Extraction failed"}
    except Exception as e:
        return {"success": False, "error": str(e)}
