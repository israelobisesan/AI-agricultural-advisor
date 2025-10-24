import os
import io
import google.generativeai as genai
from PIL import Image
from flask import Flask, render_template, url_for, redirect, request, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_mail import Mail, Message as FlaskMailMessage
from itsdangerous import URLSafeTimedSerializer
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from datetime import datetime
from flask import send_from_directory
from deep_translator import GoogleTranslator
from flask import Flask
import requests

# --- New TTS Imports ---
from gtts import gTTS
from transformers import VitsModel, AutoTokenizer
import torch
import soundfile as sf
import re

# Load environment variables from .env file
load_dotenv()

# --- App and Database Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key-that-you-will-change')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
AUDIO_FOLDER = 'static/audio'
app.config['AUDIO_FOLDER'] = AUDIO_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)


# --- Email Configuration ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_FROM_ADDRESS')

# --- Gemini AI Configuration ---
genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
text_model = genai.GenerativeModel("gemini-2.5-flash")
vision_model = genai.GenerativeModel("gemini-2.5-flash")

# --- MMS-TTS for Yoruba Configuration ---
# You only need to load the model and tokenizer once when the app starts.
try:
    model_id = "facebook/mms-tts-yor"

    yoruba_tts_model = VitsModel.from_pretrained(model_id)
    yoruba_tts_tokenizer = AutoTokenizer.from_pretrained(model_id)
    print("MMS-TTS model loaded successfully.")
except Exception as e:
    print(f"Error loading MMS-TTS model: {e}")
    yoruba_tts_model = None
    yoruba_tts_tokenizer = None


# --- Flask Extensions and Security ---
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# For generating and confirming email tokens
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- Database Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    chat_sessions = db.relationship('ChatSession', backref='user', lazy=True)

class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), default='New Chat')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    messages = db.relationship('ChatMessage', backref='chat_session', lazy=True)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    sender = db.Column(db.String(10), nullable=False)
    text = db.Column(db.String, nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    '''return User.query.get(int(user_id))'''
    return db.session.get(User, int(user_id))


def send_confirmation_email(user_email):
    try:
        token = s.dumps(user_email, salt='email-confirm')
        msg = FlaskMailMessage('Confirm Your Email', sender=os.getenv('MAIL_FROM_ADDRESS'), recipients=[user_email])
        link = url_for('confirm_email', token=token, _external=True)
        msg.body = f'Your verification link is {link}'
        mail.send(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# --- Routes ---
@app.route('/')
@login_required
def index():
    user_sessions = ChatSession.query.filter_by(user_id=current_user.id).order_by(ChatSession.created_at.desc()).all()
    # If the user has no sessions, create one
    if not user_sessions:
        new_session = ChatSession(user_id=current_user.id)
        db.session.add(new_session)
        db.session.commit()
        user_sessions = [new_session] # Update the list with the newly created session
    
    # Get the latest session or the session from query parameter
    session_id = request.args.get('session_id')
    if session_id:
        current_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        if not current_session:
            # If the session doesn't exist or doesn't belong to the user, redirect to the latest session
            return redirect(url_for('index', session_id=user_sessions[0].id))
    else:
        current_session = user_sessions[0] # Default to the latest session
    
    # Fetch messages for the current session
    messages = ChatMessage.query.filter_by(session_id=current_session.id).order_by(ChatMessage.created_at).all()
    
    return render_template(
        'index.html',
        sessions=user_sessions,
        current_session=current_session,
        messages=messages
    )


@app.route('/new_chat', methods=['GET', 'POST'])
@login_required
def new_chat():
    new_session = ChatSession(user_id=current_user.id)
    db.session.add(new_session)
    db.session.commit()
    return redirect(url_for('index', session_id=new_session.id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not email or not password:
            flash('Email and password are required!', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('An account with this email already exists.', 'danger')
            return redirect(url_for('register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        send_confirmation_email(email)

        return render_template('confirm.html')
    return render_template('register.html')

@app.route('/confirm_email/<token>')
def confirm_email(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)
        user = User.query.filter_by(email=email).first()
        if user:
            user.is_verified = True
            db.session.commit()
            flash('Your account has been successfully verified! You can now log in.', 'success')
        else:
            flash('The confirmation link is invalid.', 'danger')
    except:
        flash('The confirmation link has expired or is invalid.', 'danger')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            if user.is_verified:
                login_user(user)
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Please confirm your email address before logging in.', 'warning')
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


def clean_text_for_tts(text):
    """
    Cleans up text by removing markdown and replacing newline characters.
    """
    # Remove markdown bold/italic formatting
    cleaned_text = re.sub(r'\*\*|__|\*', '', text)
    # Replace newlines with a space for better TTS flow
    cleaned_text = cleaned_text.replace('\n', ' ')
    return cleaned_text.strip()


def generate_tts_audio(text, lang):
    """Generates a TTS audio file and returns its URL."""
    cleaned_text = clean_text_for_tts(text)
    audio_filename = f"response-{datetime.now().strftime('%Y%m%d%H%M%S')}-{lang}.mp3"
    audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
    
    if lang == 'yo' and yoruba_tts_model and yoruba_tts_tokenizer:
        # Use MMS-TTS for Yoruba
        try:
            inputs = yoruba_tts_tokenizer(cleaned_text, return_tensors="pt")
            with torch.no_grad():
                waveforms = yoruba_tts_model(**inputs).waveform

            sf.write(audio_path, waveforms.squeeze().cpu().numpy(), 16000)
            return url_for('static', filename=f'audio/{audio_filename}')
        except Exception as e:
            print(f"MMS-TTS generation failed: {e}")
            return None

    elif lang == 'en':
        # Use gTTS for English
        try:
            tts = gTTS(text=cleaned_text, lang='en', slow=False)
            tts.save(audio_path)
            return url_for('static', filename=f'audio/{audio_filename}')
        except Exception as e:
            print(f"gTTS generation failed: {e}")
            return None
    
    return None


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.json
    user_message = data.get('message')
    session_id = data.get('session_id')
    image_filename = data.get('image_filename')
    selected_language = data.get('language', 'en')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400

    chat_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not chat_session:
        return jsonify({'error': 'Chat session not found or does not belong to user'}), 404

    # Save the user's message to the database
    user_message_obj = ChatMessage(
        session_id=session_id,
        sender='user',
        text=user_message,
        image_filename=image_filename
    )
    db.session.add(user_message_obj)
    db.session.commit()

    # --- Update chat session title if it's still default ---
    chat_session = db.session.get(ChatSession, session_id)
    if chat_session.title == "New Chat":
        # Use first 6 words of user's message as title
        words = user_message.split()
        new_title = " ".join(words[:6]) + ("..." if len(words) > 6 else "")
        chat_session.title = new_title
        db.session.commit()


    try:
        # Step 1: Translate user input to English for Gemini
        if selected_language == 'yo':
            user_message_en = GoogleTranslator(source='yo', target='en').translate(user_message)
        else:
            user_message_en = user_message
            # Decide output language instruction
        if selected_language == 'yo':
            language_instruction = "Respond fully in Yoruba language, keeping explanations simple and clear."
        else:
            language_instruction = "Respond fully in English language, keeping explanations simple and clear."

        
        # Step 2: Generate response with Gemini
        system_prompt = (
            "You are an AI-powered agricultural advisor for Yoruba farmers "
            "(South-West Nigeria). Always provide detailed, step-by-step, practical guidance "
            "tailored to the regionÃ¢â‚¬â„¢s soils, climate, and common crops. "
            
            "You must be able to advise farmers on: "
            "1) Soil and land preparation, "
            "2) Crop selection and planting practices, "
            "3) Fertilizer and organic manure use, "
            "4) Pest and disease management (common in Yoruba land), "
            "5) Irrigation and water management, "
            "6) Harvesting, storage, and processing, "
            "7) Farm location planning and agribusiness opportunities, "
            "8) Seasonal and climate-related farming decisions. "
            "When farmers ask questions or follow-up questions, you must: "
            "- Always answer as a trusted farming advisor, not as an AI or system. "
            "- Never talk about how AI works or how responses are generated. "
            "- Always keep the context in agriculture"
            "- If a farmer asks 'Will this work?', confirm and explain why in farming terms "


            "Always explain recommendations in a farmer-friendly way, including local best "
            "practices, Yoruba regional conditions (loamy/ferrallitic soils, rainy season AprilÃ¢â‚¬â€œOctober), "
            "and examples with major crops such as cassava, yam, maize, cocoa, citrus, and vegetables. "

            "If a user asks about topics outside agriculture, politely decline and remind them "
            "that you are designed to support Yoruba farmers with agricultural advice."
            f"{language_instruction}"
       
        )

        
        if image_filename:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            img = Image.open(image_path)
            
            full_prompt = [
                system_prompt,
                user_message_en,
                img
            ]
            response = vision_model.generate_content(full_prompt)
        else:
            full_prompt = [
                system_prompt,
                user_message_en
            ]
            response = text_model.generate_content(full_prompt)
            
        ai_response_text_en = response.text
        
        # Step 3: Translate Gemini's response back to the user's language
        if selected_language == 'yo':
            ai_response_text_final = GoogleTranslator(source='en', target='yo').translate(ai_response_text_en)
        else:
            ai_response_text_final = ai_response_text_en

        # Step 4: Save the AI's final response to the database
        ai_message_obj = ChatMessage(session_id=session_id, sender='ai', text=ai_response_text_final)
        db.session.add(ai_message_obj)
        db.session.commit()

        # Step 5: Generate audio file using the new function
        audio_url = generate_tts_audio(ai_response_text_final, selected_language)

        return jsonify({'response': ai_response_text_final, 'audio_url': audio_url})
    
    except Exception as e:
        print(f"Error during AI generation or translation: {e}")
        return jsonify({'response': 'Sorry, I could not process your request at this time.', 'audio_url': None})

@app.route('/api/chat_history/<int:session_id>')
@login_required
def api_get_chat_history(session_id):
    chat_session = db.session.query(ChatSession).filter_by(id=session_id, user_id=current_user.id).first()
    if chat_session:
        messages = [{'sender': m.sender, 'text': m.text, 'image_filename': m.image_filename} for m in chat_session.messages]
        return jsonify({'messages': messages})
    else:
        return jsonify({'error': 'Chat session not found or does not belong to user'}), 404

@app.route('/api/upload_image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(file_path)
            return jsonify({'image_filename': filename})
        except Exception as e:
            print(f"Error saving file: {e}")
            return jsonify({'error': 'Failed to save file'}), 500
    return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/audio/<path:filename>')
def audio_file(filename):
    return send_from_directory(app.config['AUDIO_FOLDER'], filename)


'''app = Flask(__name__)

@app.route('/')
def home():
    return "Hello, Render!"'''


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)