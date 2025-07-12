from flask import Flask, request, jsonify
from gpt4all import GPT4All
import os
import time
import json
from datetime import datetime, date, timedelta

current_deck = None
app = Flask(__name__)

# Full path to your local GGUF model
model_path = "/home/joshuag/models/Meta-Llama-3-8B-Instruct.Q4_0.gguf"

# Initialize GPT4All with full path
model = GPT4All(model_name=os.path.basename(model_path), model_path=os.path.dirname(model_path))

# Load deck (assumed format in cards.json)
with open("cards.json") as f:
    cards = json.load(f)

LEARNING_STEPS = [1, 10]  # in minutes
GRADUATING_INTERVAL = 1  # days
EASY_INTERVAL = 4        # days
MIN_EASE_FACTOR = 1.3
DEFAULT_EASE_FACTOR = 2.5
INTERVAL_MODIFIER = 1.0

current_card = None

# Time adjustment on load
def adjust_intervals():
    try:
        with open("config.json") as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {"last_run": str(date.today())}

    last_run = datetime.strptime(config.get("last_run"), "%Y-%m-%d").date()
    today = date.today()
    days_passed = (today - last_run).days

    if days_passed > 0:
        for card in cards:
            if card.get("state") == "Review":
                card["interval"] = max(0, card.get("interval", 0) - days_passed)

    config["last_run"] = str(today)
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)

adjust_intervals()

def get_next_card():
    now = datetime.now()
    due_cards = []

    for card in cards:
        state = card.get("state", "New")
        due_time = card.get("due_time")
        is_due = not due_time or datetime.fromisoformat(due_time) <= now

        if state == "New":
            card.update({
                "state": "Learning",
                "learning_step": 0,
                "ease_factor": DEFAULT_EASE_FACTOR,
                "interval": 0,
                "lapses": 0,
                "due_time": now.isoformat()
            })
            return card
        elif state == "Learning" and is_due:
            due_cards.append(card)
        elif state == "Learning" and not is_due:
            print(f"⏳ Skipping {card['front']} — due at {due_time}")
        elif state == "Review" and card.get("interval", 0) <= 0 and is_due:
            due_cards.append(card)

    if due_cards:
        # Sort by soonest due_time
        due_cards.sort(key=lambda c: datetime.fromisoformat(c.get("due_time", now.isoformat())))
        return due_cards[0]

    return None

def update_learning(card, rating):
    now = datetime.now()

    if rating == "Again":
        card["learning_step"] = 0
        card["due_time"] = (now + timedelta(minutes=1)).isoformat()
    elif rating == "Hard":
        card["due_time"] = (now + timedelta(minutes=10)).isoformat()
    elif rating in ["Good", "Easy"]:
        card["learning_step"] = card.get("learning_step", 0) + 1
        card["due_time"] = now.isoformat()  # Immediately available

    # Graduation
    if card["learning_step"] >= len(LEARNING_STEPS):
        card["state"] = "Review"
        card["ease_factor"] = card.get("ease_factor", DEFAULT_EASE_FACTOR)
        card["interval"] = EASY_INTERVAL if rating == "Easy" else GRADUATING_INTERVAL
        card["lapses"] = 0
        card["due_time"] = now.isoformat()

    return card


def update_review(card, rating):
    ef = card.get("ease_factor", DEFAULT_EASE_FACTOR)
    interval = card.get("interval", 1)

    if rating == "Again":
        card["state"] = "Learning"
        card["learning_step"] = 0
        card["lapses"] = card.get("lapses", 0) + 1
        card["ease_factor"] = max(MIN_EASE_FACTOR, ef - 0.2)
        card["interval"] = 0
    else:
        if rating == "Hard":
            card["ease_factor"] = max(MIN_EASE_FACTOR, ef - 0.15)
            new_interval = max(1, interval * 1.2)
        elif rating == "Good":
            new_interval = max(1, interval * ef)
        elif rating == "Easy":
            card["ease_factor"] = ef + 0.15
            new_interval = max(1, interval * ef * 1.3)

        card["interval"] = int(new_interval * INTERVAL_MODIFIER)
    return card

def review_card(card):
    print(f"\n📖 Card: {card['front']}")
    simulate_time_passage()
    input("Press Enter to see the answer...")
    print(f"💡 Answer: {card['back']}")

    if card["state"] == "Learning":
        print(f"Step {card.get('learning_step', 0)+1}/{len(LEARNING_STEPS)} in Learning")
    elif card["state"] == "Review":
        print(f"Interval: {card['interval']}d | EF: {card['ease_factor']:.2f} | Lapses: {card.get('lapses', 0)}")

    print("Rate this card: [1]Again [2]Hard [3]Good [4]Easy")
    choice = input("Your choice: ").strip()
    rating_map = {"1": "Again", "2": "Hard", "3": "Good", "4": "Easy"}
    rating = rating_map.get(choice, "Good")

    if card["state"] == "New":
        card["state"] = "Learning"
        card["learning_step"] = 0

    if card["state"] == "Learning":
        card = update_learning(card, rating)
    elif card["state"] == "Review":
        card = update_review(card, rating)

    return card


def run_session(cards):
    session_active = True

    def is_last_card_in_deck(card, cards):
        return sum(1 for c in cards if c["state"] in ("New", "Learning") and c != card) == 0


    def handle_new_card(card):
        # Initialize new card properties
        card["state"] = "Learning"
        card["learning_step"] = 0
        card["lapses"] = 0
        card["ease_factor"] = DEFAULT_EASE_FACTOR
        card["interval"] = 0
        print(f"📘 New card → Learning: {card['front']}")
        # Directly handle it as a learning card now
        return handle_learning_card(card)

    def handle_learning_card(card):
        print(f"📘 Learning card: {card['front']}")
        rating = get_rating()

        # Auto graduate if last card and rating is Good or Easy
        if rating in ("Good", "Easy") and is_last_card_in_deck(card, cards):
            print("✨ Last card in deck, auto-graduating.")
            card["learning_step"] = len(LEARNING_STEPS)
            card["state"] = "Review"
            card["ease_factor"] = card.get("ease_factor", DEFAULT_EASE_FACTOR)
            card["interval"] = EASY_INTERVAL if rating == "Easy" else GRADUATING_INTERVAL
            card["lapses"] = 0
        else:
            card = update_learning(card, rating)

        # Decide if this card should be repeated
        # Repeat only if rated Again or Hard and still learning
        if rating in ("Again", "Hard") and card["state"] == "Learning":
            repeat = True
        else:
            repeat = False

        return card, repeat

    def get_rating():
        rating_map = {
            "1": "Again",
            "2": "Hard",
            "3": "Good",
            "4": "Easy",
            "again": "Again",
            "hard": "Hard",
            "good": "Good",
            "easy": "Easy",
        }
        while True:
            choice = input("Your rating (1=Again, 2=Hard, 3=Good, 4=Easy): ").strip().lower()
            rating = rating_map.get(choice)
            if rating:
                return rating
            print("Invalid input, try again.")

    while session_active:
        session_active = False
        next_round = []

        for card in cards:
            state = card.get("state")

            if state == "New":
                card, repeat = handle_new_card(card)
                session_active = True
                if repeat:
                    next_round.append(card)

            elif state == "Learning":
                card, repeat = handle_learning_card(card)
                session_active = True
                if repeat:
                    next_round.append(card)

            elif state == "Review":
                # Only show card if interval <= 0 (due)
                if card.get("interval", 0) <= 0:
                    print(f"📗 Review card: {card['front']}")
                    rating = get_rating()
                    card = update_review(card, rating)
                    session_active = True
                else:
                    # Decrease interval by 1 day for simulation purposes
                    card["interval"] = max(0, card["interval"] - 1)

                if card["state"] == "Review" and card.get("interval", 0) == 0:
                    next_round.append(card)



        if not next_round:
            print("🎉 All cards graduated or none due now.")
            break

        cards = next_round

    print("✅ Session complete.")
    return cards

def evaluate_answer_with_gpt(question, correct_answer, user_answer):
    print(f"🧠 Evaluating:\n  Q: {current_card['front']}\n  A: {current_card['back']}\n  User: {user_answer}")
    prompt = f"""
    You are evaluating an answer to a flashcard.

    Question: {question}
    Expected (Correct) Answer: {correct_answer}
    User Answer: {user_answer}

    Evaluate the user's answer **against the expected correct answer**.

    Return a JSON object **only** in this format:
    {{
    "score": 1-4,  // 1=Again, 2=Hard, 3=Good, 4=Easy
    "feedback": "<Brief explanation of how well the user answered>",
    "correct": "{correct_answer}"
    }}

    Only include the expected answer in the "correct" field, not the question or anything else.
    Start your response with the JSON object and nothing else.
    """


    with model.chat_session():
        raw_output = model.generate(prompt, max_tokens=250).strip()
        print(f"🤖 GPT Response:\n{raw_output}")

    try:
        json_start = raw_output.find("{")
        json_end = raw_output.rfind("}") + 1
        parsed = eval(raw_output[json_start:json_end])

        # 🛡️ Validate and clamp the score
        score = parsed.get("score", 1)
        score = max(1, min(4, int(score)))  # Clamp to 1–4
        parsed["score"] = score

    except Exception as e:
        parsed = {
            "score": 1,
            "feedback": "Could not parse GPT response.",
            "correct": correct_answer
        }

    return parsed


@app.route('/review', methods=['POST'])
def review():
    global current_card, current_deck

    data = request.json
    action = data.get("action")

    if action == "answer":
        if not current_card:
            return jsonify({"error": "No active card"}), 400

        user_answer = data.get("answer", "")
        eval_result = evaluate_answer_with_gpt(
        current_card["front"],
        current_card["back"],
        user_answer
        )


        score_map = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
        rating = score_map.get(eval_result["score"], "Again")

        if current_card["state"] == "Learning":
            current_card = update_learning(current_card, rating)
        elif current_card["state"] == "Review":
            current_card = update_review(current_card, rating)

        with open("cards.json", "w") as f:
            json.dump(cards, f, indent=2)

        return jsonify(eval_result)
    
    elif action == "continue":
        current_card = get_next_card()
        if not current_card or "front" not in current_card:
            return jsonify({"error": "No more cards or malformed card"}), 404
        return jsonify({"question": current_card["front"]})

    else:
        return jsonify({"error": "Invalid action"}), 400

if __name__ == "__main__":
    app.run(port=5000)
