"""
Quick Training Script for Incremental T5 Fine-tuning

This script performs incremental fine-tuning on a small dataset to quickly
fix specific issues without retraining on the full 24K+ examples.

Usage:
    python quick_train.py [--dataset correlation_fixes.json] [--epochs 5] [--base-checkpoint trained/checkpoint-3]

Benefits:
    - Fast training (5-10 minutes vs 1-2 hours)
    - Preserves existing knowledge
    - Quick iteration for fixing specific patterns
    - Minimal GPU memory required

Author: AI Assistant
Date: October 2025
"""

import json
import os
import argparse
from datasets import Dataset
from transformers import (
    T5ForConditionalGeneration, 
    T5Tokenizer, 
    Trainer, 
    TrainingArguments,
    DataCollatorForSeq2Seq
)
import torch
from datetime import datetime

def load_quick_dataset(filepath="training/bldg1/correlation_fixes.json"):
    """Load the small quick-fix dataset."""
    print(f"Loading quick-fix dataset from: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} examples for quick training")
    return data

def prepare_training_data(data):
    """Prepare data for T5 format."""
    inputs = []
    outputs = []
    
    for example in data:
        question = example.get("question", "")
        sparql = example.get("sparql", "")
        
        if question and sparql:
            inputs.append(f"Translate to SPARQL: {question}")
            outputs.append(sparql)
    
    print(f"Prepared {len(inputs)} training pairs")
    return inputs, outputs

def create_dataset(inputs, outputs):
    """Create dataset (no split needed for small dataset)."""
    dataset = Dataset.from_dict({
        "input_text": inputs,
        "target_text": outputs
    })
    print(f"Dataset size: {len(dataset)} examples")
    return dataset

def preprocess_function(examples, tokenizer, max_input_length=512, max_target_length=512):
    """Tokenize inputs and outputs."""
    model_inputs = tokenizer(
        examples["input_text"],
        max_length=max_input_length,
        truncation=True,
        padding="max_length"
    )
    
    with tokenizer.as_target_tokenizer():
        labels = tokenizer(
            examples["target_text"],
            max_length=max_target_length,
            truncation=True,
            padding="max_length"
        )
    
    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

def quick_train(
    dataset_path="training/bldg1/correlation_fixes.json",
    base_checkpoint="trained/checkpoint-3",
    epochs=10,
    batch_size=2,
    learning_rate=3e-5,
    output_dir="trained/quick-fix"
):
    """
    Quick incremental training on small dataset.
    
    Args:
        dataset_path: Path to small quick-fix dataset
        base_checkpoint: Path to existing model checkpoint (to continue from)
        epochs: Number of epochs (more epochs OK for small dataset)
        batch_size: Batch size (smaller for quick training)
        learning_rate: Learning rate (lower for fine-tuning)
        output_dir: Output directory
    """
    
    print("=" * 70)
    print(f"Quick Incremental Training - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"Dataset: {dataset_path}")
    print(f"Base Model: {base_checkpoint}")
    print(f"Epochs: {epochs}")
    print(f"Batch Size: {batch_size}")
    print(f"Learning Rate: {learning_rate}")
    print("=" * 70)
    
    # Device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\nUsing device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    
    # Load data
    print("\n" + "=" * 70)
    print("Loading Quick-Fix Dataset")
    print("=" * 70)
    data = load_quick_dataset(dataset_path)
    
    # Prepare data
    print("\n" + "=" * 70)
    print("Preparing Training Data")
    print("=" * 70)
    inputs, outputs = prepare_training_data(data)
    
    # Show examples
    print("\nExample training pairs:")
    for i in range(min(2, len(inputs))):
        print(f"\n--- Example {i+1} ---")
        print(f"Input:  {inputs[i][:100]}...")
        print(f"Output: {outputs[i][:100]}...")
    
    # Create dataset
    print("\n" + "=" * 70)
    print("Creating Dataset")
    print("=" * 70)
    dataset = create_dataset(inputs, outputs)
    
    # Load existing model
    print("\n" + "=" * 70)
    print("Loading Existing Model")
    print("=" * 70)
    
    if not os.path.exists(base_checkpoint):
        print(f"⚠️  Warning: Base checkpoint not found: {base_checkpoint}")
        print("    Using t5-base as base model instead")
        base_checkpoint = "t5-base"
    
    print(f"Loading from: {base_checkpoint}")
    tokenizer = T5Tokenizer.from_pretrained(base_checkpoint)
    model = T5ForConditionalGeneration.from_pretrained(base_checkpoint)
    
    # Tokenize
    print("\n" + "=" * 70)
    print("Tokenizing Dataset")
    print("=" * 70)
    tokenized_dataset = dataset.map(
        lambda x: preprocess_function(x, tokenizer),
        batched=True,
        remove_columns=["input_text", "target_text"]
    )
    
    # Data collator
    data_collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model)
    
    # Training arguments
    print("\n" + "=" * 70)
    print("Setting Up Training")
    print("=" * 70)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_dir = f"{output_dir}/checkpoint_{timestamp}"
    
    training_args = TrainingArguments(
        output_dir=checkpoint_dir,
        overwrite_output_dir=True,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=learning_rate,
        weight_decay=0.01,
        save_strategy="epoch",
        logging_dir=f"{checkpoint_dir}/logs",
        logging_steps=5,
        save_total_limit=3,
        push_to_hub=False,
        report_to="none",
        warmup_steps=2
    )
    
    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset,
        tokenizer=tokenizer,
        data_collator=data_collator
    )
    
    # Train
    print("\n" + "=" * 70)
    print("Starting Quick Training")
    print("=" * 70)
    print(f"Training on {len(dataset)} examples for {epochs} epochs")
    print("This should be very fast (5-10 minutes)...\n")
    
    trainer.train()
    
    # Save
    print("\n" + "=" * 70)
    print("Saving Model")
    print("=" * 70)
    final_dir = f"{output_dir}/checkpoint-quick-fix"
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    print(f"Model saved to: {final_dir}")
    
    # Test
    print("\n" + "=" * 70)
    print("Testing Updated Model")
    print("=" * 70)
    
    test_questions = [
        "What is the correlation between Zone_Air_Humidity_Sensor_5.04, CO2_Level_Sensor_5.04, and PM10_Level_Sensor_Atmospheric_5.04 sensors?",
        "Get data for humidity and temperature sensors in room 5.02."
    ]
    
    model.to(device)
    
    for i, question in enumerate(test_questions, 1):
        print(f"\n--- Test {i} ---")
        print(f"Question: {question}")
        
        input_text = f"Translate to SPARQL: {question}"
        input_ids = tokenizer(input_text, return_tensors="pt").input_ids.to(device)
        
        outputs = model.generate(
            input_ids, 
            max_length=512, 
            num_beams=4, 
            early_stopping=True
        )
        sparql = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        print(f"Generated SPARQL:")
        print(sparql)
    
    print("\n" + "=" * 70)
    print("Quick Training Complete!")
    print("=" * 70)
    print(f"Model location: {final_dir}")
    print(f"Checkpoint location: {checkpoint_dir}")
    print("\nTo deploy this quick-fix model:")
    print(f"1. Copy {final_dir} to trained/checkpoint-3")
    print(f"2. Restart nl2sparql service")
    print("\nCommands:")
    print(f"  cd c:\\Users\\suhas\\Documents\\GitHub\\OntoBot\\Transformers\\t5_base")
    print(f"  Copy-Item -Path \"{final_dir}\" -Destination \"trained\\checkpoint-3\" -Recurse -Force")
    print(f"  cd ..\\..")
    print(f"  docker-compose -f docker-compose.bldg1.yml restart nl2sparql")
    print("=" * 70)

def main():
    parser = argparse.ArgumentParser(description="Quick incremental T5 training")
    parser.add_argument("--dataset", type=str, 
                       default="training/bldg1/correlation_fixes.json",
                       help="Path to quick-fix dataset")
    parser.add_argument("--base-checkpoint", type=str, 
                       default="trained/checkpoint-3",
                       help="Base model checkpoint to continue from")
    parser.add_argument("--epochs", type=int, default=10,
                       help="Number of epochs (more OK for small dataset)")
    parser.add_argument("--batch-size", type=int, default=2,
                       help="Batch size")
    parser.add_argument("--learning-rate", type=float, default=3e-5,
                       help="Learning rate (lower for fine-tuning)")
    parser.add_argument("--output-dir", type=str, default="trained/quick-fix",
                       help="Output directory")
    
    args = parser.parse_args()
    
    quick_train(
        dataset_path=args.dataset,
        base_checkpoint=args.base_checkpoint,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        output_dir=args.output_dir
    )

if __name__ == "__main__":
    main()
