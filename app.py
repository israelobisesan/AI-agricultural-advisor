import os
import io
import json
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

# --- TTS Imports ---
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
text_model = genai.GenerativeModel("gemini-3.1-flash-lite")
vision_model = genai.GenerativeModel("gemini-3.1-flash-lite")

# --- MMS-TTS for Yoruba Configuration ---
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
    audio_url = db.Column(db.Text, nullable=True)  # Stores a JSON list of audio URLs
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def send_confirmation_email(user_email):
    try:
        token = s.dumps(user_email, salt='email-confirm')
        msg = FlaskMailMessage('Confirm Your Email', sender=os.getenv('MAIL_FROM_ADDRESS'), recipients=[user_email])
        link = url_for('confirm_email', token=token, _external=True)
        msg.body = f'Your verification link is {link}'
        mail.send(msg)
    except Exception as e:
        flash(f'Error sending confirmation email: {e}', 'danger')

def send_reset_email(user_email, link):
    try:
        msg = FlaskMailMessage('Password Reset Request', sender=os.getenv('MAIL_FROM_ADDRESS'), recipients=[user_email])
        msg.body = f'To reset your password, click: {link}\n\nThis link expires in 1 hour.'
        mail.send(msg)
    except Exception as e:
        flash(f'Email delivery failed ({e}).', 'warning')

@app.route('/landing')
def landing():
    return redirect(url_for('home'))

# --- Routes ---
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    return render_template('landing.html')

@app.route('/chat')
def chat():
    if current_user.is_authenticated:
        user_sessions = ChatSession.query.filter_by(user_id=current_user.id).order_by(ChatSession.created_at.desc()).all()
        if not user_sessions:
            new_session = ChatSession(user_id=current_user.id)
            db.session.add(new_session)
            db.session.commit()
            user_sessions = [new_session]
        
        session_id = request.args.get('session_id')
        if session_id:
            current_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
            if not current_session:
                return redirect(url_for('chat', session_id=user_sessions[0].id))
        else:
            current_session = user_sessions[0]
        
        messages = ChatMessage.query.filter_by(session_id=current_session.id).order_by(ChatMessage.created_at).all()
        
        return render_template(
            'index.html',
            sessions=user_sessions,
            current_session=current_session,
            messages=messages
        )
    
    return render_template('index.html', sessions=[], current_session=None, messages=[])


@app.route('/new_chat', methods=['GET', 'POST'])
@login_required
def new_chat():
    new_session = ChatSession(user_id=current_user.id)
    db.session.add(new_session)
    db.session.commit()
    return redirect(url_for('chat', session_id=new_session.id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not email or not password:
            flash('Email and password are required!', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            if existing_user.is_verified:
                flash('An account with this email already exists.', 'danger')
                return redirect(url_for('register'))
            else:
                db.session.delete(existing_user)
                db.session.commit()

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        token = s.dumps(email, salt='email-confirm')
        verify_link = url_for('confirm_email', token=token, _external=True)

        return render_template('confirm.html', verify_link=verify_link)
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
        return redirect(url_for('chat'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            if user.is_verified:
                login_user(user)
                flash('Login successful!', 'success')
                return redirect(url_for('chat'))
            else:
                flash('Please confirm your email address before logging in.', 'warning')
        else:
            flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = s.dumps(email, salt='password-reset')
            link = url_for('reset_password', token=token, _external=True)
            return render_template('forgot_password.html', reset_link=link)
        else:
            flash('If that email is registered, a password reset link has been sent.', 'success')
            return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('chat'))
    try:
        email = s.loads(token, salt='password-reset', max_age=3600)
    except:
        flash('The password reset link has expired or is invalid.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        if not password or len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('reset_password.html', token=token)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)
        
        user = User.query.filter_by(email=email).first()
        if user:
            hashed = bcrypt.generate_password_hash(password).decode('utf-8')
            user.password = hashed
            db.session.commit()
            flash('Your password has been updated! You can now log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Account not found.', 'danger')
            return redirect(url_for('forgot_password'))
    
    return render_template('reset_password.html', token=token)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --- TTS Helper Functions ---

def clean_text_for_tts(text):
    """Cleans markdown and newlines from text before TTS."""
    cleaned_text = re.sub(r'\*\*|__|\*', '', text)
    cleaned_text = cleaned_text.replace('\n', ' ')
    return cleaned_text.strip()


def split_text_into_chunks(text, max_chars=300):
    """
    Splits text into chunks at sentence boundaries so TTS doesn't fail on long text.
    Returns a list of strings, each under max_chars.
    """
    # Split on sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If a single sentence is already too long, hard-split at word boundaries
        if len(sentence) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            words = sentence.split()
            for word in words:
                if len(current_chunk) + len(word) + 1 > max_chars:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = word
                else:
                    current_chunk += (" " if current_chunk else "") + word
        elif len(current_chunk) + len(sentence) + 1 > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += (" " if current_chunk else "") + sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text]


def generate_tts_audio(text, lang):
    cleaned_text = clean_text_for_tts(text)
    audio_urls = []
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')

    if lang == 'en':
        audio_filename = f"response-{timestamp}-0-{lang}.mp3"
        audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
        try:
            tts = gTTS(text=cleaned_text, lang='en', slow=False)
            tts.save(audio_path)
            audio_urls.append(url_for('static', filename=f'audio/{audio_filename}'))
        except Exception as e:
            print(f"gTTS failed: {e}")
        return audio_urls

    if lang == 'yo' and yoruba_tts_model and yoruba_tts_tokenizer:
        chunks = split_text_into_chunks(cleaned_text, max_chars=5000)
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            audio_filename = f"response-{timestamp}-{i}-{lang}.mp3"
            audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
            try:
                inputs = yoruba_tts_tokenizer(chunk, return_tensors="pt")
                with torch.no_grad():
                    waveforms = yoruba_tts_model(**inputs).waveform
                sf.write(audio_path, waveforms.squeeze().cpu().numpy(), 16000)
                audio_urls.append(url_for('static', filename=f'audio/{audio_filename}'))
            except Exception as e:
                print(f"MMS-TTS chunk {i} failed: {e}")
                continue

    return audio_urls


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json
    user_message = data.get('message')
    session_id = data.get('session_id')
    image_filename = data.get('image_filename')
    selected_language = data.get('language', 'en')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    if current_user.is_authenticated:
        chat_session = ChatSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        if not chat_session:
            return jsonify({'error': 'Chat session not found or does not belong to user'}), 404
        
        user_message_obj = ChatMessage(
            session_id=session_id,
            sender='user',
            text=user_message,
            image_filename=image_filename
        )
        db.session.add(user_message_obj)
        db.session.commit()
        
        chat_session = db.session.get(ChatSession, session_id)
        if chat_session.title == "New Chat":
            words = user_message.split()
            new_title = " ".join(words[:6]) + ("..." if len(words) > 6 else "")
            chat_session.title = new_title
            db.session.commit()
    
    try:
        if selected_language == 'yo':
            language_instruction = (
                "\n\nCRITICAL INSTRUCTION: You MUST respond ENTIRELY in proper Yoruba language. "
                "Use correct Yoruba orthography with appropriate diacritical marks (ẹ, ọ, ṣ, á, à, é, è, etc.). "
                "Write naturally as a native Yoruba speaker would. "
                "Keep explanations simple and clear for farmers. "
                "DO NOT mix English with Yoruba. ONLY Yoruba language."
            )
        else:
            language_instruction = (
                "\n\nCRITICAL INSTRUCTION: You MUST respond ENTIRELY in clear, simple English. "
                "DO NOT use Yoruba language in your response. "
                "Provide practical advice suitable for farmers in simple English only."
            )
        
        system_prompt = (
            "You are an AI-powered agricultural advisor for Yoruba farmers "
            "(South-West Nigeria). Always provide detailed, step-by-step, practical guidance "
            "tailored to the region's soils, climate, and common crops. "
            
            "You must be able to advise farmers on: "
            "1) Soil and land preparation, "
            "2) Crop selection and planting practices, "
            "3) Fertilizer and organic manure use, "
            "4) Pest and disease management, "
            "5) Irrigation and water management, "
            "6) Harvesting, storage, and processing, "
            "7) Farm location planning and agribusiness opportunities, "
            "8) Seasonal and climate-related farming decisions. "
            
            "When farmers ask questions or follow-up questions, you must: "
            "- Always answer as a trusted farming advisor, not as an AI or system. "
            "- Never talk about how AI works or how responses are generated. "
            "- Always keep the context in agriculture. "
            "- If a farmer asks 'Will this work?', confirm and explain why in farming terms. "
            
            "Always explain recommendations in a farmer-friendly way, including local best "
            "practices, Yoruba regional conditions (loamy/ferrallitic soils, rainy season April–October), "
            "and examples with major crops such as cassava, yam, maize, "
            "cocoa, citrus, and vegetables. "
            
            "If a user asks about topics outside agriculture, politely decline and remind them "
            "that you are designed to support Yoruba farmers with agricultural advice."
            f"{language_instruction}"
        )
        
        if image_filename:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
            img = Image.open(image_path)
            full_prompt = [system_prompt, user_message, img]
            response = vision_model.generate_content(full_prompt)
        else:
            full_prompt = [system_prompt, user_message]
            response = text_model.generate_content(full_prompt)
        
        ai_response_text = response.text
        
        if current_user.is_authenticated:
            ai_message_obj = ChatMessage(
                session_id=session_id,
                sender='ai',
                text=ai_response_text,
                audio_url=None
            )
            db.session.add(ai_message_obj)
            db.session.commit()
            message_id = ai_message_obj.id
        else:
            message_id = None
        
        return jsonify({
            'response': ai_response_text,
            'message_id': message_id,
            'language': selected_language
        })
    
    except Exception as e:
        print(f"Error during AI generation: {e}")
        error_message = (
            "Má à bínú, mi ò lè ṣe ìbéèrè rẹ ní àkókò yìí."
            if selected_language == 'yo'
            else "Sorry, I could not process your request at this time."
        )
        return jsonify({'response': error_message, 'message_id': None})


@app.route('/api/generate_audio', methods=['POST'])
def api_generate_audio():
    data = request.json
    message_id = data.get('message_id')
    language = data.get('language', 'en')

    if message_id and current_user.is_authenticated:
        message = ChatMessage.query.get(message_id)
        if not message:
            return jsonify({'error': 'Message not found'}), 404

        chat_session = ChatSession.query.get(message.session_id)
        if not chat_session or chat_session.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        if message.audio_url:
            try:
                cached = json.loads(message.audio_url)
                return jsonify({'audio_urls': cached})
            except Exception:
                return jsonify({'audio_urls': [message.audio_url]})

        text = message.text
    else:
        text = data.get('text')
        if not text:
            return jsonify({'error': 'No text provided for guest audio'}), 400

    try:
        audio_urls = generate_tts_audio(text, language)

        if audio_urls:
            if message_id and current_user.is_authenticated:
                message = ChatMessage.query.get(message_id)
                if message:
                    message.audio_url = json.dumps(audio_urls)
                    db.session.commit()
            return jsonify({'audio_urls': audio_urls})
        else:
            return jsonify({'error': 'Failed to generate audio'}), 500

    except Exception as e:
        print(f"Error generating audio: {e}")
        return jsonify({'error': 'Failed to generate audio'}), 500


@app.route('/api/chat_history/<int:session_id>')
@login_required
def api_get_chat_history(session_id):
    chat_session = db.session.query(ChatSession).filter_by(id=session_id, user_id=current_user.id).first()
    if chat_session:
        messages = [{
            'sender': m.sender,
            'text': m.text,
            'image_filename': m.image_filename,
            'audio_url': m.audio_url  # Raw JSON string — JS will parse it
        } for m in chat_session.messages]
        return jsonify({'messages': messages})
    else:
        return jsonify({'error': 'Chat session not found or does not belong to user'}), 404

@app.route('/api/upload_image', methods=['POST'])
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


@app.errorhandler(500)
def internal_error(error):
    import traceback
    tb = traceback.format_exc()
    print(f"INTERNAL SERVER ERROR:\n{tb}")
    return jsonify({'error': 'Internal server error', 'traceback': tb}), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True,)