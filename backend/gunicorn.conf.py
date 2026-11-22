def post_worker_init(worker):
    app = worker.wsgi
    if app.config["DOCUMENT_JOBS"]:
        from app.services.document_jobs import start_document_workers

        start_document_workers(app)
