from http.server import BaseHTTPRequestHandler
import json
import requests
import re
from urllib.parse import urlparse, parse_qs

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        url = query_components.get("url", [None])[0]
        
        if not url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing url parameter")
            return

        headers = {'User-Agent': 'Mozilla/5.0...'}
        try:
            response = requests.get(url, headers=headers)
            match = re.search(r"setVideoUrlHigh\('(.*?)'\)", response.text)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            if match:
                self.wfile.write(json.dumps({"streamUrl": match.group(1)}).encode())
            else:
                self.wfile.write(json.dumps({"error": "Failed"}).encode())
        except Exception as e:
            self.wfile.write(json.dumps({"error": str(e)}).encode())
