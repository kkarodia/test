import os
import json
import base64
import threading
import time
import sys
import io
import tempfile

from flask import Flask, render_template, Response, jsonify, send_from_directory, request
import requests

# Google Speech-to-Text imports
from google.cloud import speech_v1p1beta1 as speech




def load_credentials():
    """
    Load Google Cloud credentials from environment variable.
    Creates a temporary credentials file for authentication.
    """
    try:
        # Get the credentials from environment variable
        credentials_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        
        if not credentials_json:
            print("ERROR: No credentials found in environment variable")
            return None

        # Try to parse the JSON
        try:
            credentials_dict = json.loads(credentials_json)
        except json.JSONDecodeError:
            print("ERROR: Invalid JSON in credentials")
            return None

        # Create a temporary file to store credentials
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_file:
            json.dump(credentials_dict, temp_file)
            temp_file.flush()
            credentials_path = temp_file.name

        # Set the environment variable to point to the temporary file
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path
        print(f"Credentials loaded successfully at {credentials_path}")
        return credentials_path

    except Exception as e:
        print(f"CRITICAL ERROR loading credentials: {e}")
        return None

# Call this early in your application startup
credentials_file = load_credentials()
if not credentials_file:
    print("FATAL: Could not load Google Cloud credentials")

app = Flask(__name__, static_folder='static')

# Configuration
N8N_WEBHOOK_URL = os.environ.get(
    'N8N_WEBHOOK_URL', 
    "https://kkarodia.app.n8n.cloud/webhook/eb567b24-6461-4e58-b761-746ccf6b52ea"
)

# Global variables
transcription_queue = []
final_transcript = []
is_transcribing = False

def send_transcript_to_webhook(transcript):
    """
    Send the transcript to the N8N webhook
    
    :param transcript: The full transcript text
    :return: Response from the webhook
    """
    try:
        payload = {
            "transcript": transcript,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        headers = {"Content-Type": "application/json"}
        response = requests.post(N8N_WEBHOOK_URL, 
                                 data=json.dumps(payload), 
                                 headers=headers)
        
        print(f"Webhook response status: {response.status_code}")
        print(f"Webhook response: {response.text}")
        
        return response
    except Exception as e:
        print(f"Error sending transcript to webhook: {e}")
        return None

def transcribe_audio_file(content):
    """
    Transcribe the audio file using Google Speech-to-Text
    
    :param content: Bytes of the audio file
    :return: Transcription text
    """
    try:
        # Create a client
        client = speech.SpeechClient()
        
        # Configure the speech recognition request
        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000,  # Adjust based on your audio
            language_code="en-US",
            enable_automatic_punctuation=True,
            model="video",  # Use a model optimized for video/audio with background noise
        )
        
        # Perform the transcription
        response = client.recognize(config=config, audio=audio)
        
        # Extract transcripts
        transcripts = []
        for result in response.results:
            transcripts.append(result.alternatives[0].transcript)
        
        return " ".join(transcripts)
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/start_transcription', methods=['POST'])
def start_transcription():
    global is_transcribing, final_transcript
    is_transcribing = True
    final_transcript = []  # Reset final transcript
    
    # Check if audio file is present in the request
    if 'audio' not in request.files:
        return jsonify({"error": "No audio file uploaded"}), 400
    
    audio_file = request.files['audio']
    
    try:
        # Read the audio file content
        audio_content = audio_file.read()
        
        # Transcribe the audio
        transcript = transcribe_audio_file(audio_content)
        
        # Store and process transcript
        if transcript:
            final_transcript.append(transcript)
            return jsonify({"transcript": transcript})
        else:
            return jsonify({"error": "No transcript generated"}), 400
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/stop_transcription')
def stop_transcription():
    global is_transcribing, final_transcript
    is_transcribing = False
    
    # Send final transcript to webhook when stopping
    if final_transcript:
        full_transcript = " ".join(final_transcript)
        send_transcript_to_webhook(full_transcript)
    
    return jsonify({"status": "Transcription stopped"})

@app.route('/get_final_transcript')
def get_final_transcript():
    global final_transcript
    transcript = " ".join(final_transcript)
    return jsonify({"transcript": transcript})

@app.route('/clear_transcript')
def clear_transcript():
    global final_transcript
    final_transcript = []
    return jsonify({"status": "Transcript cleared"})

# Heroku compatibility: use PORT environment variable
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
