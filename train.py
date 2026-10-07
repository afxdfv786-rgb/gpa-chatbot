"""
train.py - trains the local intent classifier.

Run from the project root:

    python training/train.py

Steps:
  1. load data/intents.json
  2. turn every pattern into a (sentence, intent) training pair
  3. build a TF-IDF vectorizer (word + character n-grams)
  4. train a Logistic Regression classifier
  5. save model/model.pkl and model/vectorizer.pkl

Everything runs on your own computer - no internet or API key is needed.
"""

import json
import os
import pickle
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import FeatureUnion

# Make "chatbot" importable when running `python training/train.py`
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from chatbot.nlp import preprocess_for_model  # noqa: E402  (same cleaning as at chat time)

INTENTS_PATH = os.path.join(BASE_DIR, "data", "intents.json")
MODEL_DIR = os.path.join(BASE_DIR, "model")
MODEL_PATH = os.path.join(MODEL_DIR, "model.pkl")
VECTORIZER_PATH = os.path.join(MODEL_DIR, "vectorizer.pkl")


def load_training_data(path=INTENTS_PATH):
    """Return (sentences, labels) from intents.json."""
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    sentences, labels = [], []
    for intent in data["intents"]:
        for pattern in intent["patterns"]:
            sentences.append(preprocess_for_model(pattern))
            labels.append(intent["tag"])
    return sentences, labels


def build_vectorizer():
    """Word n-grams capture meaning; character n-grams tolerate typos."""
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                 token_pattern=r"(?u)\b\w+\b")),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)),
    ])


def build_classifier():
    return LogisticRegression(C=20.0, max_iter=3000, class_weight="balanced")


def train(verbose=True):
    """Train and save the model. Returns the training accuracy."""
    log = print if verbose else (lambda *a, **k: None)

    log("Loading training data...")
    sentences, labels = load_training_data()
    log(f"  {len(sentences)} training sentences, {len(set(labels))} intents")

    log("Creating TF-IDF vectorizer...")
    vectorizer = build_vectorizer()
    features = vectorizer.fit_transform(sentences)
    log(f"  {features.shape[1]} features")

    # Quick honesty check: 5-fold cross validation on unseen sentences
    if verbose:
        counts = np.bincount(np.unique(labels, return_inverse=True)[1])
        folds = int(min(5, counts.min()))
        if folds >= 2:
            cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
            scores = cross_val_score(build_classifier(), features, labels, cv=cv)
            log(f"  Cross-validation accuracy: {scores.mean() * 100:.1f}%")

    log("Training model...")
    model = build_classifier()
    model.fit(features, labels)
    accuracy = model.score(features, labels)
    log(f"  Training accuracy: {accuracy * 100:.1f}%")

    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(MODEL_PATH, "wb") as file:
        pickle.dump(model, file)
    with open(VECTORIZER_PATH, "wb") as file:
        pickle.dump(vectorizer, file)

    log("Training completed successfully.")
    log(f"Model saved to {os.path.relpath(MODEL_PATH, BASE_DIR)}")
    log(f"Vectorizer saved to {os.path.relpath(VECTORIZER_PATH, BASE_DIR)}")
    return accuracy


if __name__ == "__main__":
    try:
        train()
    except FileNotFoundError:
        print("Could not find data/intents.json. Run this command from the project folder.")
        sys.exit(1)
