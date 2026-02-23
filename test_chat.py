import requests
import json
import sys

try:
    response = requests.post(
        'http://localhost:5000/chat',
        json={"message": "Hello from test script"},
        headers={"Content-Type": "application/json"}
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Error: {e}")
