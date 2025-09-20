from transformers import T5ForConditionalGeneration, T5Tokenizer

model = T5ForConditionalGeneration.from_pretrained("./t5-task-extractor")
tokenizer = T5Tokenizer.from_pretrained("./t5-task-extractor")


def extract_task(note):
    input_text = "extract tasks: " + note
    inputs = tokenizer(input_text, return_tensors="pt", truncation=True)
    outputs = model.generate(**inputs, max_length=256)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


print(
    extract_task(
        "Liam: Prepare the script for user testing. Need this by end of day to get it approved."
    )
)
