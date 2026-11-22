from dotenv import load_dotenv
load_dotenv()
from app import create_app

app = create_app()

if __name__ == "__main__":
    if app.config["DOCUMENT_JOBS"]:
        from app.services.document_jobs import start_document_workers

        start_document_workers(app)
    app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False),
            use_reloader=False if app.config["DOCUMENT_JOBS"] else None)
