from datasets import load_dataset
from transformers import (
    DataCollatorForSeq2Seq,
    T5ForConditionalGeneration,
    T5Tokenizer,
    Trainer,
    TrainingArguments,
)

# Load tokenizer and model
model_name = "t5-small"
tokenizer = T5Tokenizer.from_pretrained(model_name)
model = T5ForConditionalGeneration.from_pretrained(model_name)

# Load dataset
dataset = load_dataset("json", data_files="data.json")


# Preprocess function
def preprocess(example):
    input_text = "extract tasks: " + example["input"]
    target_text = example["output"]
    model_inputs = tokenizer(input_text, max_length=256, truncation=True)
    labels = tokenizer(target_text, max_length=256, truncation=True)
    model_inputs["labels"] = labels["input_ids"]
    return model_inputs


tokenized_dataset = dataset.map(preprocess, batched=False)

# Data collator
data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

# Training arguments
training_args = TrainingArguments(
    output_dir="./t5-task-extractor",
    evaluation_strategy="epoch",
    learning_rate=5e-5,
    per_device_train_batch_size=4,
    per_device_eval_batch_size=4,
    num_train_epochs=5,
    weight_decay=0.01,
    save_total_limit=2,
    predict_with_generate=True,
    logging_dir="./logs",
    logging_steps=20,
)

# Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset["train"],
    eval_dataset=tokenized_dataset["train"],  # in hackathon: train = eval
    tokenizer=tokenizer,
    data_collator=data_collator,
)

# Train
trainer.train()

# Save final model
trainer.save_model("./t5-task-extractor")
tokenizer.save_pretrained("./t5-task-extractor")
