from dotenv import load_dotenv

# Load env files before importing anything that reads os.environ at import time
# (backend.auth). load_dotenv never overwrites a variable that is already set, so the
# first file wins: .env.local (local overrides) beats .env.
load_dotenv(".env.local")
load_dotenv()

from backend.app_factory import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=4999)