def test_dependencies():
    dependencies = {
        'FastAPI': 'fastapi',
        'Uvicorn': 'uvicorn',
        'Python-Multipart': 'multipart',
        'Python-Jose': 'jose',
        'Passlib': 'passlib',
        'Python-dotenv': 'dotenv',
        'Google Auth': 'google.auth',
        'Google OAuth': 'google_auth_oauthlib',
        'Google HTTP': 'google.auth.transport.requests',
        'Google API Client': 'googleapiclient',
        'PyPDF2': 'PyPDF2',
        'pizzapi': 'pizzapi',
        'Requests': 'requests',
        'OpenAI': 'openai'
    }
    
    print("Testing dependencies...")
    print("-" * 50)
    
    all_passed = True
    for name, package in dependencies.items():
        try:
            __import__(package)
            version = __import__(package).__version__ if hasattr(__import__(package), '__version__') else 'Unknown'
            print(f" {name:<20} - Version: {version}")
        except ImportError as e:
            all_passed = False
            print(f" {name:<20} - Failed to import: {str(e)}")
        except Exception as e:
            all_passed = False
            print(f" {name:<20} - Error: {str(e)}")
    
    print("-" * 50)
    if all_passed:
        print("All dependencies are installed and working.")
    else:
        print("Some dependencies failed. Please check the errors above.")

if __name__ == "__main__":
    test_dependencies()
