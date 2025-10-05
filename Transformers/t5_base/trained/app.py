from flask import Flask, request, jsonify, render_template_string
import os
from transformers import T5Tokenizer, T5ForConditionalGeneration
import torch
from collections import deque
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize query log (stores last 50 queries)
query_log = deque(maxlen=50)

# Load the T5 model and tokenizer (configurable via env MODEL_PATH, default /app/checkpoint-3)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model_path = os.getenv("MODEL_PATH", "/app/checkpoint-3")

def _load_model(path: str):
    logger.info(f"Attempting to load model from: {path}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"MODEL_PATH does not exist: {path}")
    tok = T5Tokenizer.from_pretrained(path)
    mdl = T5ForConditionalGeneration.from_pretrained(path).to(device)
    return tok, mdl

try:
    tokenizer, model = _load_model(model_path)
    logger.info("Model and tokenizer loaded successfully")
except Exception as e:
    logger.error(f"Failed to load model at {model_path}: {e}")
    raise

# HTML template for welcome page
welcome_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NL to SPARQL Converter</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #e0eafc, #cfdef3);
            min-height: 100vh;
            padding: 40px 20px;
        }
        .container { max-width: 900px; }
        .header { text-align: center; margin-bottom: 40px; color: #1a2b49; }
        .header h1 { font-weight: 700; font-size: 2.5rem; text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.1); }
        .header p { font-size: 1.1rem; color: #4a5e83; }
        .form-box { background: white; padding: 30px; border-radius: 15px; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1); transition: transform 0.3s ease; }
        .form-box:hover { transform: translateY(-5px); }
        textarea, input[type="text"] { border-radius: 8px; box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.05); resize: vertical; }
        .btn-convert { background: linear-gradient(90deg, #007bff, #00d4ff); border: none; padding: 12px 30px; font-weight: 600; border-radius: 25px; transition: all 0.3s ease; }
        .btn-convert:hover { background: linear-gradient(90deg, #0056b3, #0099cc); transform: scale(1.05); }
        .result-box { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border-left: 5px solid #007bff; }
        .log-box { margin-top: 40px; background: white; padding: 25px; border-radius: 15px; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1); }
        .log-box h3 { color: #1a2b49; margin-bottom: 20px; }
        .log-entry { padding: 10px; background: #f1f3f5; border-radius: 8px; margin-bottom: 10px; font-size: 0.9rem; word-wrap: break-word; }
        .log-entry:hover { background: #e9ecef; transition: background 0.2s ease; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>NL to SPARQL Converter</h1>
            <p>Transform your natural language questions into SPARQL queries with our advanced T5 model.</p>
        </div>
        <div class="form-box">
            <form method="post" action="/">
                <div class="mb-3">
                    <label for="question" class="form-label fw-bold">Question</label>
                    <textarea class="form-control" id="question" name="question" rows="3" placeholder="Enter your natural language question here..." required></textarea>
                </div>
                <div class="mb-3">
                    <label for="entity" class="form-label fw-bold">Entity</label>
                    <input type="text" class="form-control" id="entity" name="entity" placeholder="e.g., brick:Heating_Ventilation_Air_Conditioning_System" required>
                </div>
                <button type="submit" class="btn btn-convert">Convert to SPARQL</button>
            </form>
            {% if sparql_query %}
                <div class="result-box mt-4">
                    <h3 class="fw-bold text-primary">Generated SPARQL Query</h3>
                    <pre class="mb-0">{{ sparql_query }}</pre>
                </div>
            {% endif %}
        </div>
        <div class="log-box">
            <h3>Recent Queries (Last 50)</h3>
            {% if logs %}
                {% for log in logs %}
                    <div class="log-entry">{{ log }}</div>
                {% endfor %}
            {% else %}
                <p class="text-muted">No queries yet. Start converting above!</p>
            {% endif %}
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""


def generate_sparql(question, entity):
    """Generate SPARQL query from question and entity."""
    input_text = f"task: generate_sparql\ninput: {question}\nentity:{entity}"
    input_ids = tokenizer.encode(
        input_text, return_tensors="pt", truncation=True, max_length=512
    ).to(device)
    outputs = model.generate(
        input_ids, max_length=150, num_beams=5, early_stopping=True
    )
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "GET":
        return render_template_string(
            welcome_template,
            logs=[
                f"{entry['time']} - {entry['question']} ({entry['entity']}) -> {entry['sparql']}"
                for entry in query_log
            ],
        )
    elif request.method == "POST":
        try:
            # Handle both JSON and form data
            if request.content_type == "application/json":
                data = request.json
                question = data.get("question")
                entity = data.get("entity")
            else:
                question = request.form.get("question")
                entity = request.form.get("entity")

            if not question or not entity:
                error_msg = "Both 'question' and 'entity' are required"
                if request.content_type == "application/json":
                    return jsonify({"error": error_msg}), 400
                return render_template_string(
                    welcome_template, sparql_query=error_msg, logs=query_log
                )

            # Generate SPARQL
            sparql_query = generate_sparql(question, entity)

            # Log the query
            log_entry = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "question": question,
                "entity": entity,
                "sparql": sparql_query,
            }
            query_log.append(log_entry)
            logger.info(f"Query translated: {question} ({entity}) -> {sparql_query}")

            # Return response
            if request.content_type == "application/json":
                return jsonify({"sparql_query": sparql_query})
            return render_template_string(
                welcome_template,
                sparql_query=sparql_query,
                logs=[
                    f"{entry['time']} - {entry['question']} ({entry['entity']}) -> {entry['sparql']}"
                    for entry in query_log
                ],
            )
        except Exception as e:
            logger.error(f"Error in translation: {e}")
            if request.content_type == "application/json":
                return jsonify({"error": str(e)}), 500
            return render_template_string(
                welcome_template, sparql_query=f"Error: {str(e)}", logs=query_log
            )


@app.route("/nl2sparql", methods=["POST"])
def nl2sparql():
    try:
        # Handle both JSON and form data
        if request.content_type == "application/json":
            data = request.json
            question = data.get("question")
            entity = data.get("entity")
        else:
            question = request.form.get("question")
            entity = request.form.get("entity")

        if not question or not entity:
            error_msg = "Both 'question' and 'entity' are required"
            if request.content_type == "application/json":
                return jsonify({"error": error_msg}), 400
            return render_template_string(
                welcome_template, sparql_query=error_msg, logs=query_log
            )

        # Generate SPARQL
        sparql_query = generate_sparql(question, entity)

        # Log the query
        log_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "entity": entity,
            "sparql": sparql_query,
        }
        query_log.append(log_entry)
        logger.info(f"Query translated: {question} ({entity}) -> {sparql_query}")

        # Return response
        if request.content_type == "application/json":
            return jsonify({"sparql_query": sparql_query})
        return render_template_string(
            welcome_template,
            sparql_query=sparql_query,
            logs=[
                f"{entry['time']} - {entry['question']} ({entry['entity']}) -> {entry['sparql']}"
                for entry in query_log
            ],
        )
    except Exception as e:
        logger.error(f"Error in translation: {e}")
        if request.content_type == "application/json":
            return jsonify({"error": str(e)}), 500
        return render_template_string(
            welcome_template, sparql_query=f"Error: {str(e)}", logs=query_log
        )


@app.route("/health", methods=["GET"])
def health():
    """Lightweight health endpoint for Docker healthcheck."""
    return jsonify({
        "status": "ok",
        "model_path": model_path,
        "device": str(device),
        "queries_cached": len(query_log)
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6005, debug=False)
