import os
import random

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

MODEL_NAME = os.environ.get("ROBERTA_MODEL", "roberta-base")
MAX_LEN = int(os.environ.get("ROBERTA_MAX_LEN", "192"))
BATCH_SIZE = int(os.environ.get("ROBERTA_BATCH", "16"))
EPOCHS = int(os.environ.get("ROBERTA_EPOCHS", "2"))
LR = float(os.environ.get("ROBERTA_LR", "2e-5"))
SEED = int(os.environ.get("ROBERTA_SEED", "42"))


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def tokenize(tokenizer, texts):
    return tokenizer(texts, truncation=True, max_length=MAX_LEN, padding="max_length", return_tensors="pt")


def train_roberta(texts, labels):
    seed_all(SEED)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)
    enc = tokenize(tokenizer, texts)
    dataset = TensorDataset(enc["input_ids"], enc["attention_mask"], torch.tensor(labels))
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)
    negatives = int((labels == 0).sum())
    positives = int((labels == 1).sum())
    total = len(labels)
    weights = torch.tensor([total / (2 * negatives), total / (2 * positives)], dtype=torch.float)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    steps = len(loader) * EPOCHS
    scheduler = get_linear_schedule_with_warmup(optimizer, int(0.1 * steps), steps)
    model.train()
    for epoch in range(EPOCHS):
        running = 0.0
        for input_ids, attention_mask, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(input_ids=input_ids, attention_mask=attention_mask).logits
            loss = loss_fn(logits, targets)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += float(loss.item())
        print(f"epoch {epoch + 1}/{EPOCHS} loss {running / len(loader):.4f}", flush=True)
    model.eval()
    return model, tokenizer


def predict_roberta(model, tokenizer, texts):
    enc = tokenize(tokenizer, texts)
    loader = DataLoader(TensorDataset(enc["input_ids"], enc["attention_mask"]), batch_size=32)
    out = []
    with torch.no_grad():
        for input_ids, attention_mask in loader:
            logits = model(input_ids=input_ids, attention_mask=attention_mask).logits
            out.append(torch.softmax(logits, dim=1)[:, 1].cpu().numpy())
    return np.concatenate(out)
