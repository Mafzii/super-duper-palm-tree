"""Flask entry point — registers REST API blueprint and SSE stream."""
import json
import time

from flask import Flask, Response, jsonify, request, stream_with_context

from crawler.job_manager import JobManager

app = Flask(__name__)
job_manager = JobManager()


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.post("/api/v1/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    if not payload.get("seed_urls"):
        return jsonify({"error": "seed_urls required"}), 400
    job = job_manager.create_job(payload)
    return jsonify({"job_id": job.job_id, "status": job.status}), 201


@app.get("/api/v1/jobs")
def list_jobs():
    jobs = job_manager.list_jobs()
    return jsonify([j.to_dict() for j in jobs])


@app.get("/api/v1/jobs/<job_id>")
def get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job.to_dict())


@app.delete("/api/v1/jobs/<job_id>")
def cancel_job(job_id: str):
    ok = job_manager.cancel_job(job_id)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"job_id": job_id, "status": "cancelling"})


# ── Results ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/jobs/<job_id>/results")
def get_results(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    with job._results_lock:
        total = len(job.results)
        start = (page - 1) * per_page
        items = job.results[start : start + per_page]
    return jsonify({
        "job_id": job_id,
        "page": page,
        "per_page": per_page,
        "total": total,
        "results": items,
    })


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.get("/api/v1/jobs/<job_id>/stream")
def stream_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404

    def generate():
        cursor = 0
        terminal = {"completed", "cancelled", "error"}
        while True:
            with job._sse_lock:
                events = job.sse_events[cursor:]
                cursor += len(events)
                current_status = job.status

            for event in events:
                yield f"data: {json.dumps(event)}\n\n"

            if current_status in terminal and not events:
                yield f"data: {json.dumps({'event': 'done', 'status': current_status})}\n\n"
                break

            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
