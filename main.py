import subprocess
import sys
import os
import shutil
import tempfile
import zipfile
import io
from pathlib import Path

try:
    import requests
except ImportError:
    print("Installing requests...")
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"], check=True)
    import requests

def download_and_extract_without_main(repo_url, extract_to):
    """Download repo ZIP and extract all files except main.py"""
    
    # Download the ZIP
    print(f"📥 Downloading repository from {repo_url}...")
    
    try:
        zip_url = f"{repo_url}/archive/main.zip"
        response = requests.get(zip_url, stream=True, timeout=30)
        if response.status_code != 200:
            zip_url = f"{repo_url}/archive/master.zip"
            response = requests.get(zip_url, stream=True, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading: {e}")
        raise
    
    print("✅ Download complete! Extracting (excluding main.py)...")
    
    # Extract ZIP manually to filter out main.py
    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        for file_info in zip_ref.infolist():
            # Skip if the file is main.py
            if file_info.filename.endswith('main.py'):
                print(f"⏭️  Skipping: {file_info.filename}")
                continue
            
            # Extract the file
            try:
                zip_ref.extract(file_info, extract_to)
            except Exception as e:
                print(f"⚠️  Warning: Could not extract {file_info.filename}: {e}")
    
    print("✅ Extraction complete (main.py excluded)!")

def download_and_run_repo():
    """Download the repo excluding main.py, and run the uvicorn server"""
    
    repo_url = "https://github.com/IntellsGamer/ha.mr"
    temp_dir = None
    original_dir = os.getcwd()
    
    try:
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp(prefix="ha_mr_")
        print(f"📁 Created temporary directory: {temp_dir}")
        
        # Download and extract without main.py
        download_and_extract_without_main(repo_url, temp_dir)
        
        # Find the extracted directory
        extracted_dirs = [d for d in os.listdir(temp_dir) 
                         if os.path.isdir(os.path.join(temp_dir, d)) 
                         and d.startswith("ha.mr-")]
        
        if not extracted_dirs:
            raise Exception("Could not find extracted repository directory")
        
        repo_path = os.path.join(temp_dir, extracted_dirs[0])
        print(f"📂 Repository extracted to: {repo_path}")
        
        # Verify main.py is not there
        main_py_path = os.path.join(repo_path, "main.py")
        if os.path.exists(main_py_path):
            print("⚠️  Warning: main.py still exists (should have been excluded)")
            os.remove(main_py_path)
            print("🗑️  Removed main.py just in case")
        else:
            print("✅ main.py successfully excluded from download!")
        
        # Change to the repository directory
        os.chdir(repo_path)
        print(f"📂 Changed working directory to: {os.getcwd()}")
        
        # Check if asgi.py exists
        if not os.path.exists("asgi.py"):
            print("🔍 Looking for asgi.py in subdirectories...")
            asgi_files = list(Path(".").rglob("asgi.py"))
            if asgi_files:
                print(f"✅ Found asgi.py at: {asgi_files[0]}")
                os.chdir(asgi_files[0].parent)
                print(f"📂 Changed working directory to: {os.getcwd()}")
            else:
                print("❌ Error: asgi.py not found in the repository!")
                available_files = [str(p) for p in Path(".").rglob("*.py")]
                print("Available Python files:")
                for f in available_files[:10]:  # Show first 10
                    print(f"  - {f}")
                if len(available_files) > 10:
                    print(f"  ... and {len(available_files) - 10} more")
                raise Exception("asgi.py not found")
        
        # Install requirements if they exist
        if os.path.exists("requirements.txt"):
            print("📦 Installing requirements from requirements.txt...")
            try:
                subprocess.run([
                    sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
                ], check=True, text=True, capture_output=True)
                print("✅ Requirements installed successfully!")
            except subprocess.CalledProcessError as e:
                print(f"⚠️  Warning: Could not install all requirements")
                if e.stderr:
                    print(f"Error: {e.stderr}")
        else:
            print("ℹ️  No requirements.txt found, skipping installation")
        
        # Run the uvicorn server using method #1
        print("\n" + "="*60)
        print("🚀 Starting uvicorn server on 0.0.0.0:30167...")
        print("="*60 + "\n")
        
        # Method #1: Using subprocess
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "asgi:app",
            "--host", "0.0.0.0",
            "--port", "30167",
            "--log-level", "info"
        ], check=True)
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading repository: {e}")
        print("Please check your internet connection and try again.")
    except zipfile.BadZipFile:
        print("❌ Error: Downloaded file is not a valid ZIP archive")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running command: {e}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"Error output: {e.stderr}")
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up temporary directory if needed
        if temp_dir and os.path.exists(temp_dir):
            try:
                keep = input("\n💾 Keep the downloaded repository? (y/n): ").lower().strip()
                if keep != 'y':
                    os.chdir(original_dir)
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"🗑️  Removed temporary directory: {temp_dir}")
                else:
                    print(f"📁 Repository kept at: {temp_dir}")
            except Exception as e:
                print(f"⚠️  Error cleaning up: {e}")

if __name__ == "__main__":
    # Check for required packages
    required_packages = ['requests', 'uvicorn']
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            print(f"📦 Installing {package}...")
            subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
            print(f"✅ {package} installed successfully!")
    
    download_and_run_repo()
