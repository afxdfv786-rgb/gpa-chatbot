# GradeMate - Offline GPA & CGPA Calculator Chatbot

A university project: a chatbot and calculator dashboard that computes semester GPA, updates CGPA and plans the GPA needed to reach a target CGPA.
**It runs completely offline. There is no API key, no cloud AI and no internet connection needed after installing the packages.**

## Features
- Semester **GPA calculator** (many courses, full calculation breakdown)
- **CGPA calculator** (update CGPA after a new semester)
- **Target CGPA planner** (required average GPA; handles "already achieved" and "impossible" targets)
- **Customizable grade scale** (edit values in the *Scale* tab, or in one place in `chatbot/calculator.py`)
- Chatbot that understands questions (what is GPA, formulas, grade points, credit hours...) using a **local Scikit-learn model**
- Guided conversation: say *Calculate CGPA* and the bot asks for each value
- You can also type everything at once: `Programming 3 A, Database 3 B+, English 2 A-`
- Modern glass-style interface, dark/light mode (remembered), mobile friendly, quick-action buttons, typing indicator, reset button

## Technologies
Python 3.9+, Flask, Scikit-learn (TF-IDF + Logistic Regression), NumPy, regular expressions, HTML / CSS / JavaScript.

## Project structure
```
project_root/
├── app.py                  Flask server (GET /, POST /chat, POST /calculate)
├── requirements.txt
├── README.md
├── data/intents.json       training sentences + replies
├── training/train.py       trains the local model
├── model/                  model.pkl and vectorizer.pkl (created by training)
├── chatbot/
│   ├── __init__.py
│   ├── calculator.py       maths engine (independent of Flask and NLP)
│   ├── nlp.py              intent model + regex number/grade extraction
│   └── chatbot.py          conversation pipeline
├── static/css/style.css
├── static/js/app.js
└── templates/index.html
```

## Installation (Windows)
Open **Command Prompt** or **PowerShell** inside the project folder (the one containing `app.py`).

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
(PowerShell may need `Set-ExecutionPolicy -Scope Process Bypass` once before activating.)

On macOS / Linux: `python3 -m venv venv && source venv/bin/activate`.

## Training the local model
```
python training/train.py
```
Expected output:
```
Loading training data...
Creating TF-IDF vectorizer...
Training model...
Training completed successfully.
Model saved to model/model.pkl
Vectorizer saved to model/vectorizer.pkl
```
A trained model is already included. If the model files are missing or were made with another scikit-learn version, the app trains a fresh one automatically on first start.

## Running the application
```
python app.py
```
Open **http://127.0.0.1:5000** in your browser. Press `Ctrl + C` in the terminal to stop.

## How the local NLP model works
1. `training/train.py` reads every sentence in `data/intents.json` and its intent label (greeting, gpa_formula, calculate_cgpa ...).
2. Sentences are cleaned (lower-case; numbers become the word `num`) and turned into numbers with **TF-IDF** (word pairs + character groups, so small typos still work).
3. A **Logistic Regression** classifier learns which words belong to which intent and is saved to `model/`.
4. At chat time `chatbot/nlp.py` loads the model, predicts the intent and its confidence (below 30% = "fallback").
5. **Regular expressions** extract course names, credit hours, grades, GPA, CGPA and target values from the message.
6. `chatbot/chatbot.py` decides what to do and calls `chatbot/calculator.py`. The answers to calculations are always computed, never hard-coded.

## Formulas
**GPA** = Σ(Grade Point × Credit Hours) ÷ Σ(Credit Hours)

**New CGPA** = (Current CGPA × Previous Credits + Semester GPA × Semester Credits) ÷ (Previous Credits + Semester Credits)

**Required GPA** = (Target CGPA × Total Final Credits − Current CGPA × Completed Credits) ÷ Remaining Credits,
where Total Final Credits = Completed + Remaining.
If the result is above 4.0 the target is not achievable; if it is 0 or less the target is already secured.

## Default grading scale
| Grade | Points | Grade | Points |
|---|---|---|---|
| A+ | 4.0 | C+ | 2.3 |
| A | 4.0 | C | 2.0 |
| A- | 3.7 | C- | 1.7 |
| B+ | 3.3 | D+ | 1.3 |
| B | 3.0 | D | 1.0 |
| B- | 2.7 | F | 0.0 |

To change it permanently edit `GRADE_SCALE` at the top of `chatbot/calculator.py`.

## Things to test
- GPA: `Programming 3 A, Database 3 B+, English 2 A-` gives **3.66** (29.3 quality points / 8 credits)
- CGPA: 3.20, 60 credits, new GPA 3.80, 15 credits gives **3.32**
- Planner: 3.20, 60 credits, target 3.40, 30 remaining gives **3.80**; target 3.90 gives "not achievable"
- Chat: `hello`, `what is gpa`, `cgpa formula`, `show grade scale`, `what are credit hours`, `thanks`, `bye`, `reset`

## Share with your group (public website)

The project is deployment-ready for a Python web host such as Render. After deployment, the host gives you a public `https://...` address that you can send to your group members. They do **not** need Python, VS Code, or the project ZIP to use the chatbot.

### Render deployment
1. Put this project in a GitHub repository.
2. In Render, create a **Web Service** and connect that repository.
3. Use these settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120`
4. Deploy. Render will provide a public HTTPS URL.
5. Share that URL with your group.

The included `render.yaml` can also be used as the deployment configuration. The `/health` endpoint is included for hosting health checks.

**Important:** This is still a self-trained/local ML chatbot. No OpenAI, Gemini, or other external AI API key is required.

## Troubleshooting
- **`python` not found** - install Python from python.org and tick "Add Python to PATH".
- **`No module named flask / sklearn`** - activate the venv (`venv\Scripts\activate`) and run `pip install -r requirements.txt`.
- **Port 5000 already in use** - change `port=5000` at the bottom of `app.py` (e.g. 5001).
- **"Cannot reach the server" in the page** - make sure `python app.py` is still running.
- **Model warning / error** - run `python training/train.py` again.
- **Custom grade scale looks wrong** - press *Restore defaults* in the Scale tab.
