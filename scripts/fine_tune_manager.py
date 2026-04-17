"""
Phase 6.5 — Federated Model Fine-Tuning Manager
=================================================
Manages the collection, formatting, and submission of domain-specific
training examples for fine-tuning the LLM on building management QA.

Workflow:
  1. Collect high-quality QA pairs from OntoSage logs (positive examples)
  2. Collect correction pairs when self-correction engine fired (negative→positive)
  3. Format into JSONL fine-tuning datasets (OpenAI / HuggingFace formats)
  4. Optionally upload to provider API (OpenAI fine-tune jobs)
  5. Track fine-tune run status and switch active model on completion

Key classes:
  ExampleCollector   — Mines conversation logs for fine-tune examples
  DatasetFormatter   — Converts to JSONL (OpenAI / HF / Alpaca formats)
  FineTuneManager    — Manages upload, training job, model switching

Usage:
    python scripts/fine_tune_manager.py --collect --output data/finetune/
    python scripts/fine_tune_manager.py --format openai --input data/finetune/raw.jsonl
    python scripts/fine_tune_manager.py --upload --model gpt-4o-mini
"""

from __future__ import annotations

import os
import json
import time
import logging
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Example types
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are OntoSage, an intelligent building management assistant.
You answer questions about sensor data, building ontologies, and smart building systems.
You use SPARQL to query ontologies and SQL to fetch time-series sensor readings.
Always be precise, use sensor names (not raw UUIDs), and provide actionable insights."""


class QAExample:
    def __init__(
        self,
        user_query: str,
        ideal_response: str,
        intent: str = "analytics",
        source: str = "log",
        correction: bool = False,
        score: float = 1.0,
    ):
        self.user_query = user_query
        self.ideal_response = ideal_response
        self.intent = intent
        self.source = source
        self.correction = correction  # from self-correction log
        self.score = score  # quality 0.0-1.0
        self.timestamp = datetime.datetime.utcnow().isoformat()

    def to_openai_format(self) -> Dict:
        """OpenAI fine-tune JSONL format (chat)."""
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.user_query},
                {"role": "assistant", "content": self.ideal_response},
            ]
        }

    def to_hf_format(self) -> Dict:
        """HuggingFace SFT trainer format."""
        return {
            "prompt": f"<s>[INST] {self.user_query} [/INST]",
            "completion": f"{self.ideal_response} </s>",
        }

    def to_alpaca_format(self) -> Dict:
        """Stanford Alpaca instruction format."""
        return {
            "instruction": self.user_query,
            "input": "",
            "output": self.ideal_response,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Example Collector
# ─────────────────────────────────────────────────────────────────────────────


class ExampleCollector:
    """Mines OntoSage conversation logs and correction logs for training examples."""

    MIN_QUALITY_SCORE = 0.7  # minimum score to include an example
    MAX_EXAMPLES = 5000  # cap to avoid huge datasets

    def collect_from_logs(self, log_dir: Path) -> List[QAExample]:
        """Scan JSONL debug logs for high-quality QA pairs."""
        examples = []
        for log_file in log_dir.glob("*.jsonl"):
            try:
                examples.extend(self._parse_log(log_file))
            except Exception as e:
                logger.warning(f"Log parse error ({log_file}): {e}")
        logger.info(f"Collected {len(examples)} potential examples from {log_dir}")
        return examples[: self.MAX_EXAMPLES]

    def _parse_log(self, log_file: Path) -> List[QAExample]:
        examples = []
        with log_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    example = self._extract_example(record)
                    if example and example.score >= self.MIN_QUALITY_SCORE:
                        examples.append(example)
                except (json.JSONDecodeError, KeyError):
                    pass
        return examples

    def _extract_example(self, record: Dict) -> Optional[QAExample]:
        """Try to extract a QA example from a log record."""
        # Format 1: {"user_message": "...", "assistant_message": "...", "intent": "..."}
        user_msg = record.get("user_message") or record.get("query") or record.get("input")
        asst_msg = record.get("assistant_message") or record.get("response") or record.get("output")
        if not user_msg or not asst_msg:
            return None

        intent = record.get("intent", "general")
        # Assign score: correction examples get higher weight
        score = 0.9 if record.get("self_corrected") else 0.8
        if len(asst_msg) < 20:
            score -= 0.3  # penalise very short responses

        return QAExample(
            user_query=str(user_msg),
            ideal_response=str(asst_msg),
            intent=intent,
            source=str(record.get("source", "log")),
            correction=bool(record.get("self_corrected", False)),
            score=max(0.0, min(1.0, score)),
        )

    def collect_seed_examples(self) -> List[QAExample]:
        """Return handcrafted seed examples for bootstrap fine-tuning."""
        seeds = [
            (
                "What is the current temperature in zone 1?",
                "The current temperature in Zone 1.01 is **22.3°C**, measured by Air Temperature Sensor 1.01 at 14:35 UTC. This is within the ASHRAE 55 comfort range (20–26°C). ✅",
                "analytics",
            ),
            (
                "List all CO2 sensors on floor 2.",
                "Floor 2 has **2 CO2 sensors**: CO2 Sensor 2.01 (Zone 2.01, UUID: uuid-co2-201) and CO2 Sensor 2.02 (Zone 2.02, UUID: uuid-co2-202). Both are connected to the MySQL sensor_data database.",
                "metadata",
            ),
            (
                "Are there any anomalies in the humidity sensors this week?",
                "⚠️ **1 anomaly detected** in Zone 1.02:\n- Relative Humidity Sensor 1.02: **78% RH** on 2024-03-04 at 09:15 (threshold: 60%). This may indicate a leakage or HVAC malfunction. Recommend inspection.",
                "anomaly",
            ),
            (
                "Generate a weekly building summary report.",
                "# Weekly Building Report (2024-03-01 to 2024-03-07)\n\n**Temperature**: Avg 22.1°C (Grade A — 97% within range)\n**Humidity**: Avg 48% RH (Grade A — 99% within range)\n**CO2**: Avg 680 ppm (Grade B — 94% below 1000 ppm)\n**Anomalies**: 2 events (1 humidity spike, 1 temperature dip)\n\n_All metrics within ASHRAE 55 comfort standards._",
                "report",
            ),
            (
                "Compare temperatures between zone 1 and zone 2.",
                "**Zone 1** (Floor 1): Avg **22.3°C**, Min 20.8°C, Max 24.1°C\n**Zone 2** (Floor 2): Avg **21.7°C**, Min 19.9°C, Max 23.5°C\n\nZone 1 is on average 0.6°C warmer. Both zones are within comfort range. No adjustments required.",
                "compare",
            ),
        ]
        return [QAExample(q, a, intent=intent, source="seed", score=1.0) for q, a, intent in seeds]


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Formatter
# ─────────────────────────────────────────────────────────────────────────────


class DatasetFormatter:
    """Formats QA examples into various fine-tuning dataset formats."""

    FORMATS = ("openai", "hf", "alpaca")

    def format(self, examples: List[QAExample], fmt: str) -> List[Dict]:
        if fmt == "openai":
            return [e.to_openai_format() for e in examples]
        elif fmt == "hf":
            return [e.to_hf_format() for e in examples]
        elif fmt == "alpaca":
            return [e.to_alpaca_format() for e in examples]
        else:
            raise ValueError(f"Unknown format: {fmt!r}. Valid: {self.FORMATS}")

    def write_jsonl(self, examples: List[Dict], output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(examples)} examples to {output_path}")

    def split_train_val(
        self, examples: List[QAExample], val_ratio: float = 0.1
    ) -> Tuple[List, List]:
        """Split into train/validation sets (stratified by intent)."""
        # Group by intent
        by_intent: Dict[str, List] = {}
        for ex in examples:
            by_intent.setdefault(ex.intent, []).append(ex)

        train, val = [], []
        for intent_examples in by_intent.values():
            n_val = max(1, int(len(intent_examples) * val_ratio))
            val.extend(intent_examples[:n_val])
            train.extend(intent_examples[n_val:])
        return train, val


# ─────────────────────────────────────────────────────────────────────────────
# Fine-Tune Manager
# ─────────────────────────────────────────────────────────────────────────────


class FineTuneManager:
    """Orchestrates the fine-tuning pipeline end-to-end."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._job_ids: List[str] = []

    def upload_and_train(self, dataset_path: Path) -> Optional[str]:
        """Upload JSONL file and start a fine-tune job (OpenAI)."""
        try:
            import openai

            client = openai.OpenAI(api_key=self._api_key)

            # Upload file
            with dataset_path.open("rb") as f:
                file_obj = client.files.create(file=f, purpose="fine-tune")
            logger.info(f"File uploaded: {file_obj.id}")

            # Start fine-tune job
            job = client.fine_tuning.jobs.create(
                training_file=file_obj.id,
                model=self._model,
                hyperparameters={"n_epochs": 3},
            )
            self._job_ids.append(job.id)
            logger.info(f"Fine-tune job started: {job.id}")
            return job.id

        except ImportError:
            logger.warning("openai library not installed — fine-tune upload skipped")
            return None
        except Exception as e:
            logger.error(f"Fine-tune upload failed: {e}")
            return None

    def check_job_status(self, job_id: str) -> Dict:
        """Check status of a fine-tune job."""
        try:
            import openai

            client = openai.OpenAI(api_key=self._api_key)
            job = client.fine_tuning.jobs.retrieve(job_id)
            return {
                "job_id": job_id,
                "status": job.status,
                "model": job.fine_tuned_model,
                "created_at": job.created_at,
            }
        except Exception as e:
            return {"job_id": job_id, "error": str(e)}

    def run_pipeline(
        self,
        log_dir: Path = Path("logs/"),
        output_dir: Path = Path("data/finetune/"),
        fmt: str = "openai",
        upload: bool = False,
    ) -> Dict:
        """Run the complete pipeline: collect → format → split → optionally upload."""
        collector = ExampleCollector()
        formatter = DatasetFormatter()

        # Step 1: Collect
        examples = collector.collect_from_logs(log_dir)
        seed = collector.collect_seed_examples()
        all_examples = seed + examples
        logger.info(
            f"Total examples: {len(all_examples)} " f"(seed={len(seed)}, log={len(examples)})"
        )

        # Step 2: Split
        train, val = formatter.split_train_val(all_examples)

        # Step 3: Format and write
        for split, split_examples in [("train", train), ("val", val)]:
            formatted = formatter.format(split_examples, fmt)
            out_path = output_dir / f"{fmt}_{split}.jsonl"
            formatter.write_jsonl(formatted, out_path)

        # Step 4: Upload (optional)
        job_id = None
        if upload:
            train_path = output_dir / f"{fmt}_train.jsonl"
            job_id = self.upload_and_train(train_path)

        return {
            "total_examples": len(all_examples),
            "train_examples": len(train),
            "val_examples": len(val),
            "format": fmt,
            "output_dir": str(output_dir),
            "job_id": job_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OntoSage Fine-Tune Manager")
    parser.add_argument(
        "--collect", action="store_true", help="Collect training examples from logs"
    )
    parser.add_argument("--format", choices=DatasetFormatter.FORMATS, default="openai")
    parser.add_argument("--input", default="logs/", help="Log directory")
    parser.add_argument("--output", default="data/finetune/", help="Output directory")
    parser.add_argument("--upload", action="store_true", help="Upload to OpenAI")
    parser.add_argument("--model", default="gpt-4o-mini", help="Base model for fine-tuning")
    args = parser.parse_args()

    mgr = FineTuneManager(model=args.model)
    result = mgr.run_pipeline(
        log_dir=Path(args.input),
        output_dir=Path(args.output),
        fmt=args.format,
        upload=args.upload,
    )
    print(json.dumps(result, indent=2))
