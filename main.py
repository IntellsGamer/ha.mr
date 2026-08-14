import subprocess
import sys

def run_server():
    """Run uvicorn server with specified host and port"""
    try:
        # Run uvicorn command
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "asgi:app", 
            "--host", "0.0.0.0", 
            "--port", "30167"
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running server: {e}")
    except KeyboardInterrupt:
        print("\nServer stopped by user")

if __name__ == "__main__":
    run_server()