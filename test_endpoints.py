import requests
import base64
import os
from datetime import datetime, timedelta
import json

BASE_URL = "http://localhost:8000"

def test_health():
    """Test the health endpoint"""
    response = requests.get(f"{BASE_URL}/health")
    print("\n1. Health Check:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_ask():
    """Test the question answering endpoint"""
    payload = {
        "question": "What is FastAPI?",
        "context": "FastAPI is a modern web framework for building APIs with Python."
    }
    response = requests.post(f"{BASE_URL}/ask", json=payload)
    print("\n2. Question Answering:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_email():
    """Test the email endpoint"""
    payload = {
        "to": "vsaisrinivas182000@gmail.com",
        "subject": "Test Email",
        "body": "This is a test email from the MCP server."
    }
    response = requests.post(f"{BASE_URL}/email", json=payload)
    print("\n3. Email Sending:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_meeting():
    """Test the meeting scheduling endpoint"""
    payload = {
        "title": "Test Meeting",
        "description": "This is a test meeting scheduled via MCP server.",
        "start_time": (datetime.now() + timedelta(hours=1)).isoformat(),
        "duration_minutes": 30,
        "attendees": ["vsaisrinivas182000@gmail.com"]
    }
    response = requests.post(f"{BASE_URL}/meeting", json=payload)
    print("\n4. Meeting Scheduling:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_pdf():
    """Test the PDF processing endpoint"""
    sample_pdf = "JVBERi0xLjcKCjEgMCBvYmogICUgZW50cnkgcG9pbnQKPDwKICAvVHlwZSAvQ2F0YWxvZwogIC9QYWdlcyAyIDAgUgo+PgplbmRvYmoKCjIgMCBvYmoKPDwKICAvVHlwZSAvUGFnZXMKICAvTWVkaWFCb3ggWyAwIDAgMjAwIDIwMCBdCiAgL0NvdW50IDEKICAvS2lkcyBbIDMgMCBSIF0KPj4KZW5kb2JqCgozIDAgb2JqCjw8CiAgL1R5cGUgL1BhZ2UKICAvUGFyZW50IDIgMCBSCiAgL1Jlc291cmNlcyA8PAogICAgL0ZvbnQgPDwKICAgICAgL0YxIDQgMCBSIAogICAgPj4KICA+PgogIC9Db250ZW50cyA1IDAgUgo+PgplbmRvYmoKCjQgMCBvYmoKPDwKICAvVHlwZSAvRm9udAogIC9TdWJ0eXBlIC9UeXBlMQogIC9CYXNlRm9udCAvVGltZXMtUm9tYW4KPj4KZW5kb2JqCgo1IDAgb2JqICAlIHBhZ2UgY29udGVudAo8PAogIC9MZW5ndGggNDQKPj4Kc3RyZWFtCkJUCjcwIDUwIFRECi9GMSAxMiBUZgooSGVsbG8sIFdvcmxkKSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCgp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTAgMDAwMDAgbiAKMDAwMDAwMDA3OSAwMDAwMCBuIAowMDAwMDAwMTczIDAwMDAwIG4gCjAwMDAwMDAzMDEgMDAwMDAgbiAKMDAwMDAwMDM4MCAwMDAwMCBuIAp0cmFpbGVyCjw8CiAgL1NpemUgNgogIC9Sb290IDEgMCBSCj4+CnN0YXJ0eHJlZgo0OTIKJSVFT0YK"
    
    payload = {
        "pdf_data": sample_pdf
    }
    response = requests.post(f"{BASE_URL}/pdf", json=payload)
    print("\n5. PDF Processing:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def test_search():
    """Test the web search endpoint"""
    payload = {
        "query": "What is Python programming?",
        "num_results": 3
    }
    response = requests.post(f"{BASE_URL}/search", json=payload)
    print("\n6. Web Search:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")


def test_pizza():
    """Test the pizza ordering endpoint."""
    if os.environ.get("PIZZA_LIVE_MODE", "").lower() not in {"true", "1", "yes", "on"}:
        print("\n7. Pizza Ordering:")
        print("Skipped (set PIZZA_LIVE_MODE=true to place a live order).")
        return

    payload = {
        "customer": {
            "first_name": os.environ.get("PIZZA_TEST_FIRST_NAME", "Test"),
            "last_name": os.environ.get("PIZZA_TEST_LAST_NAME", "User"),
            "email": os.environ.get("PIZZA_TEST_EMAIL", "test@example.com"),
            "phone": os.environ.get("PIZZA_TEST_PHONE", "1234567890"),
        },
        "address": {
            "street": os.environ.get("PIZZA_TEST_STREET", "1 Example Way"),
            "city": os.environ.get("PIZZA_TEST_CITY", "Austin"),
            "region": os.environ.get("PIZZA_TEST_REGION", "TX"),
            "postal_code": os.environ.get("PIZZA_TEST_POSTAL", "73301"),
        },
        "items": [
            {
                "code": os.environ.get("PIZZA_TEST_ITEM_CODE", "14SCREEN"),
                "quantity": int(os.environ.get("PIZZA_TEST_ITEM_QTY", "1")),
            }
        ],
        "special_instructions": os.environ.get("PIZZA_TEST_INSTRUCTIONS", "Leave at the door."),
    }

    response = requests.post(f"{BASE_URL}/pizza", json=payload)
    print("\n7. Pizza Ordering:")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")

def main():
    print("Starting MCP Server End-to-End Tests")
    print("=" * 50)
    
    try:
        test_health()
        test_ask()
        test_email()
        test_meeting()
        test_pdf()
        test_search()
        test_pizza()
    except requests.exceptions.ConnectionError:
        print("\n Error: Could not connect to the server. Make sure it's running on http://localhost:8000")
    except Exception as e:
        print(f"\n Error during testing: {str(e)}")

    print("\nEnd of Tests")
    print("=" * 50)

if __name__ == "__main__":
    main()
