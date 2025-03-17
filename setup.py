"""
Helper script for setting up the GitHub Folder ZIP API
"""
import os
import sys
import subprocess
import platform

def check_dependencies():
    """Check if all dependencies are installed correctly"""
    try:
        import fastapi
        import uvicorn
        import dotenv
        print("✅ Core dependencies are installed")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        return False
    
    try:
        import aiohttp
        print("✅ aiohttp is installed")
    except ImportError:
        print("⚠️ aiohttp is not installed. The app may fall back to synchronous mode.")
        
        if platform.system() == "Windows":
            print("\nℹ️ On Windows, you might need Microsoft Visual C++ Build Tools to install aiohttp.")
            print("   You can download it from: https://visualstudio.microsoft.com/visual-cpp-build-tools/")
            print("   Alternatively, you can try pip install aiohttp --only-binary=:all:")
        
        choice = input("Do you want to try installing aiohttp again? (y/n): ")
        if choice.lower() == 'y':
            try:
                if platform.system() == "Windows":
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "--only-binary=:all:"])
                else:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp"])
                print("✅ aiohttp installed successfully")
            except subprocess.CalledProcessError:
                print("❌ Failed to install aiohttp")
                print("   The app will fall back to synchronous mode")
    
    return True

def setup_env_file():
    """Set up the .env file if it doesn't exist"""
    if not os.path.exists('.env'):
        if os.path.exists('.env.example'):
            print("ℹ️ Creating .env file from .env.example")
            with open('.env.example', 'r') as f_example:
                example_content = f_example.read()
            
            with open('.env', 'w') as f_env:
                f_env.write(example_content)
                
            print("✅ Created .env file. Please edit it to add your GitHub token.")
        else:
            print("❌ .env.example file not found")
    else:
        print("✅ .env file already exists")

def main():
    """Main setup function"""
    print("Setting up GitHub Folder ZIP API...")
    
    # Check dependencies
    if not check_dependencies():
        print("\nPlease install the required dependencies:")
        print("pip install -r requirements.txt")
        return
    
    # Setup .env file
    setup_env_file()
    
    print("\nSetup complete! You can now run the app with:")
    print("python main.py")
    
    choice = input("Do you want to run the app now? (y/n): ")
    if choice.lower() == 'y':
        print("\nStarting the app...")
        os.system(f"{sys.executable} main.py")

if __name__ == "__main__":
    main()
