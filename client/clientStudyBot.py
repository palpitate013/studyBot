import requests
import subprocess

SERVER_URL = "http://localhost:5000/review"

def speak(text):
    subprocess.run(["termux-tts-speak", text])

def listen():
    result = subprocess.run(["termux-speech-to-text"], stdout=subprocess.PIPE)
    return result.stdout.decode().strip()

def submit_answer(answer):
    response = requests.post(SERVER_URL, json={"action": "answer", "answer": answer})
    if response.ok:
        data = response.json()
        feedback = f"{data['feedback']}. The correct answer is: {data['correct']}. Therefore your Score is: {data['score']}."
        print(f"\n✅ Feedback:\n   ➤ {feedback}")
        speak(feedback)
    else:
        error = response.json().get("error", "Unknown error")
        print("❌ Failed to evaluate answer:", error)
        speak("Failed to evaluate answer.")

def continue_next():
    response = requests.post(SERVER_URL, json={"action": "continue"})
    if response.ok:
        try:
            data = response.json()
            question = data["question"]
            print(f"\n🔹 Next Question: {question}")
            speak(f"Next Question: {question}")
            return question
        except ValueError:
            print("❌ No JSON in response.")
            speak("No valid question received.")
            return None
    else:
        try:
            error_msg = response.json().get("error", "Unknown error")
        except ValueError:
            error_msg = response.text or "No response body"
        print("🎉 Review complete or error:", error_msg)
        return None

def run():
    question = continue_next()
    while question:
        answer = listen()
        submit_answer(answer)

        print("\n🔁 Type 'continue' to proceed or anything else to quit: ")
        proceed = listen().strip().lower()
        if proceed != "continue":
            break

        question = continue_next()

if __name__ == "__main__":
    run()
