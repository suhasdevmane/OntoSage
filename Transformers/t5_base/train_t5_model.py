"""
T5 Model Training Script for NL2SPARQL

This script trains a T5 model on the building dataset to convert
natural language questions into SPARQL queries.

Dataset Structure:
{
    "question": "What is the correlation between sensors X, Y, Z?",
    "entities": ["bldg:SensorX", "bldg:SensorY", "bldg:SensorZ"],
    "sparql": "SELECT ?sensor ?timeseriesId WHERE { ... }"
}

Usage:
    python train_t5_model.py [--base-model t5-base] [--epochs 3] [--batch-size 4]

Author: AI Assistant
Date: October 2025
"""

import json
import os
import argparse
from datasets import Dataset, DatasetDict
from transformers import (
    T5ForConditionalGeneration, 
    T5Tokenizer, 
    Trainer, 
    TrainingArguments,
    DataCollatorForSeq2Seq
)
import torch
from datetime import datetime

def load_training_data(filepath="training/bldg1/bldg1_dataset_extended.json"):
    """Load the training dataset from JSON."""
    print(f"Loading training data from: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} training examples")
    return data

def prepare_training_data(data):
    """
    Prepare training data for T5.
    
    Input format: "Translate to SPARQL: {question}"
    Output format: "{sparql}"
    """
    inputs = []
    outputs = []
    
    for example in data:
        question = example.get("question", "")
        sparql = example.get("sparql", "")
        
        if question and sparql:
            # Format as T5 translation task
            inputs.append(f"Translate to SPARQL: {question}")
            outputs.append(sparql)
    
    print(f"Prepared {len(inputs)} training pairs")
    return inputs, outputs

def create_dataset(inputs, outputs, train_ratio=0.95):
    """Create train/validation split."""
    split_idx = int(len(inputs) * train_ratio)
    
    train_dataset = Dataset.from_dict({
        "input_text": inputs[:split_idx],
        "target_text": outputs[:split_idx]
    })
    
    val_dataset = Dataset.from_dict({
        "input_text": inputs[split_idx:],
        "target_text": outputs[split_idx:]
    })
    
    dataset_dict = DatasetDict({
        "train": train_dataset,
        "validation": val_dataset
    })
    
    print(f"Train examples: {len(train_dataset)}")
    print(f"Validation examples: {len(val_dataset)}")
    
    return dataset_dict

def preprocess_function(examples, tokenizer, max_input_length=512, max_target_length=512):
    """Tokenize inputs and outputs for T5."""
    model_inputs = tokenizer(
        examples["input_text"],
        max_length=max_input_length,
        truncation=True,
        padding="max_length"
    )
    
    # Tokenize targets
    with tokenizer.as_target_tokenizer():
        labels = tokenizer(
            examples["target_text"],
            max_length=max_target_length,
            truncation=True,
            padding="max_length"
        )
    
    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

def train_model(
    base_model="t5-base",
    epochs=3,
    batch_size=4,
    learning_rate=5e-5,
    output_dir="trained",
    data_path="training/bldg1/bldg1_dataset_extended.json"
):
    """Main training function."""
    
    print("=" * 70)
    print(f"T5 NL2SPARQL Training - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"Base Model: {base_model}")
    print(f"Epochs: {epochs}")
    print(f"Batch Size: {batch_size}")
    print(f"Learning Rate: {learning_rate}")
    print(f"Output Directory: {output_dir}")
    print("=" * 70)
    
    # Check for GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nUsing device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    
    # Load data
    print("\n" + "=" * 70)
    print("Loading Training Data")
    print("=" * 70)
    data = load_training_data(data_path)
    
    # Prepare data
    print("\n" + "=" * 70)
    print("Preparing Training Pairs")
    print("=" * 70)
    inputs, outputs = prepare_training_data(data)
    
    # Create dataset
    print("\n" + "=" * 70)
    print("Creating Dataset Split")
    print("=" * 70)
    dataset = create_dataset(inputs, outputs)
    
    # Load tokenizer and model
    print("\n" + "=" * 70)
    print("Loading Model and Tokenizer")
    print("=" * 70)
    print(f"Loading {base_model}...")
    tokenizer = T5Tokenizer.from_pretrained(base_model)
    model = T5ForConditionalGeneration.from_pretrained(base_model)
    
    # Tokenize dataset
    print("\n" + "=" * 70)
    print("Tokenizing Dataset")
    print("=" * 70)
    tokenized_dataset = dataset.map(
        lambda x: preprocess_function(x, tokenizer),
        batched=True,
        remove_columns=["input_text", "target_text"]
    )
    
    # Data collator
    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        model=model
    )
    
    # Training arguments
    print("\n" + "=" * 70)
    print("Setting Up Training")
    print("=" * 70)
    
    # Create checkpoint directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_dir = f"{output_dir}/checkpoint_{timestamp}"
    
    training_args = TrainingArguments(
        output_dir=checkpoint_dir,
        overwrite_output_dir=True,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=0.01,
        save_strategy="epoch",
        evaluation_strategy="epoch",
        logging_dir=f"{checkpoint_dir}/logs",
        logging_steps=50,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        push_to_hub=False,
        report_to="none"
    )
    
    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["validation"],
        tokenizer=tokenizer,
        data_collator=data_collator
    )
    
    # Train
    print("\n" + "=" * 70)
    print("Starting Training")
    print("=" * 70)
    print("This may take a while...\n")
    
    trainer.train()
    
    # Save final model
    print("\n" + "=" * 70)
    print("Saving Final Model")
    print("=" * 70)
    final_model_dir = f"{output_dir}/checkpoint-final"
    trainer.save_model(final_model_dir)
    tokenizer.save_pretrained(final_model_dir)
    print(f"Model saved to: {final_model_dir}")
    
    # Evaluation
    print("\n" + "=" * 70)
    print("Final Evaluation")
    print("=" * 70)
    eval_results = trainer.evaluate()
    print(f"Validation Loss: {eval_results['eval_loss']:.4f}")
    
    # Test with example
    print("\n" + "=" * 70)
    print("Testing Model")
    print("=" * 70)
    test_question = "What is the correlation between Zone_Air_Humidity_Sensor_5.04, CO2_Level_Sensor_5.04, and PM10_Level_Sensor_Atmospheric_5.04 sensors?"
    print(f"Test Question: {test_question}")
    
    input_text = f"Translate to SPARQL: {test_question}"
    input_ids = tokenizer(input_text, return_tensors="pt").input_ids.to(device)
    model.to(device)
    
    outputs = model.generate(input_ids, max_length=512, num_beams=4, early_stopping=True)
    predicted_sparql = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    print(f"\nGenerated SPARQL:\n{predicted_sparql}")
    
    print("\n" + "=" * 70)
    print("Training Complete!")
    print("=" * 70)
    print(f"Final model location: {final_model_dir}")
    print(f"Checkpoint location: {checkpoint_dir}")
    print("\nTo use this model:")
    print(f"1. Copy {final_model_dir} to your deployment location")
    print(f"2. Update your docker-compose.yml to mount this checkpoint")
    print(f"3. Restart the nl2sparql service")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Train T5 model for NL2SPARQL")
    parser.add_argument("--base-model", type=str, default="t5-base", 
                       help="Base T5 model (t5-small, t5-base, t5-large)")
    parser.add_argument("--epochs", type=int, default=3, 
                       help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4, 
                       help="Batch size for training")
    parser.add_argument("--learning-rate", type=float, default=5e-5, 
                       help="Learning rate")
    parser.add_argument("--output-dir", type=str, default="trained", 
                       help="Output directory for model")
    parser.add_argument("--data-path", type=str, 
                       default="training/bldg1/bldg1_dataset_extended.json",
                       help="Path to training data JSON")
    
    args = parser.parse_args()
    
    train_model(
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        output_dir=args.output_dir,
        data_path=args.data_path
    )

if __name__ == "__main__":
    main()
