import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
import jwt
import requests
import hashlib
from functools import wraps
from supabase import create_client, Client # <--- ADDED: Supabase imports

app = Flask(__name__)

# --- Configuration ---
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "https://macaulaywebsblog.netlify.app")
CORS(app, origins=FRONTEND_ORIGIN, methods=["GET", "POST", "PUT", "DELETE"], headers=["Content-Type", "Authorization"])

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "your_super_secret_jwt_key_please_change_this_in_production!")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Supabase Configuration - STORE THESE SECURELY AS ENVIRONMENT VARIABLES ON RENDER!
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") # This is your 'anon public' key

# Validate Supabase credentials
if not SUPABASE_URL or not SUPABASE_KEY:
    print("WARNING: Supabase URL or Key not set. Supabase features will not work.")
    # In a real production app, you might want to exit or raise an error here
    # to prevent the app from running without crucial dependencies.
    supabase = None # Set to None if not configured, handle gracefully in endpoints
else:
    # Initialize Supabase client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Supabase client initialized.")


# --- In-Memory Data Stores (Removed for posts, retained for dummy users) ---

# Hashed password for the dummy user. In production, use `bcrypt` or `scrypt`.
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

users = {
    "macaulaydavid88@gmail.com": {
        "password_hash": hash_password("password123"), # Storing hashed password
        "id": "user-001",
        "email": "macaulaydavid88@gmail.com"
    }
}

# posts = [] # <--- REMOVED: Posts will now be stored in Supabase

# --- JWT Utility Functions ---

def generate_jwt_token(user_id, email):
    """Generates a JWT token for a given user."""
    payload = {
        "userId": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24) # Token expires in 24 hours
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_jwt_token(token):
    """Verifies a JWT token and returns the payload if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return {"message": "Token expired"}, 401
    except jwt.InvalidTokenError:
        return {"message": "Invalid token"}, 401
    except Exception as e:
        return {"message": f"Token verification error: {str(e)}"}, 401

# --- Authentication Decorator ---

def auth_required(f):
    """Decorator to protect routes, ensuring a valid JWT is present."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"message": "Authorization token is missing!"}), 401

        try:
            token = auth_header.split(" ")[1] # Expects "Bearer <token>"
        except IndexError:
            return jsonify({"message": "Token format is 'Bearer <token>'"}), 401

        payload = verify_jwt_token(token)
        if isinstance(payload, tuple): # If verify_jwt_token returned an error tuple
            return jsonify({"message": payload[0]["message"]}), payload[1]

        # Attach user info from token payload to request object (optional, but useful)
        request.user_id = payload.get("userId")
        request.user_email = payload.get("email")

        return f(*args, **kwargs)
    return decorated_function

# --- API Endpoints ---

@app.route('/', methods=['GET'])
def home():
    """Simple root route to check if the backend is running."""
    return "Blog Backend API is running! Access specific endpoints for functionality."

@app.route('/api/signin', methods=['POST'])
def signin():
    """
    Handles publisher login.
    Expects JSON: {"email": "...", "password": "..."}
    Returns JSON with JWT token, user_id, and email on success.
    """
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = users.get(email)
    if user and user["password_hash"] == hash_password(password): # Verify hashed password
        token = generate_jwt_token(user["id"], user["email"])
        return jsonify({"token": token, "userId": user["id"], "email": user["email"]})
    return jsonify({"message": "Invalid credentials"}), 401

@app.route('/api/verify-token', methods=['GET'])
@auth_required
def verify_token_endpoint():
    """
    Endpoint for frontend to verify if a stored token is still valid.
    Uses the auth_required decorator to do the heavy lifting.
    """
    # If auth_required didn't return an error, the token is valid.
    return jsonify({"message": "Token is valid", "userId": request.user_id, "email": request.user_email})


@app.route('/api/posts', methods=['POST'])
@auth_required # Only authenticated users can create posts
def create_post():
    """
    Handles creating a new blog post in Supabase.
    Expects JSON: {"title": "...", "content": "...", "imageUrl": "..." (optional)}
    The author_id and author_email are taken from the authenticated user's token.
    """
    if not supabase:
        return jsonify({"message": "Supabase client not initialized. Check environment variables."}), 500

    data = request.json
    title = data.get("title")
    content = data.get("content")
    image_url = data.get("imageUrl")

    if not title or not content:
        return jsonify({"message": "Title and content are required"}), 400

    try:
        # Insert data into Supabase. Note the snake_case for column names.
        response = supabase.table('posts').insert({
            "title": title,
            "content": content,
            "author_id": request.user_id,
            "author_email": request.user_email,
            "image_url": image_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_modified_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        # Supabase returns data in response.data for successful inserts
        # It's a list, so take the first element if you expect one record
        new_post_from_db = response.data[0]
        return jsonify({"message": "Post created successfully", "post": new_post_from_db}), 201

    except Exception as e:
        print(f"Error creating post in Supabase: {e}")
        return jsonify({"message": f"Failed to create post: {str(e)}"}), 500

@app.route('/api/posts', methods=['GET'])
def get_posts():
    """
    Returns all stored blog posts from Supabase.
    """
    if not supabase:
        return jsonify({"message": "Supabase client not initialized. Check environment variables."}), 500

    try:
        # Fetch all posts from Supabase, ordered by created_at descending
        response = supabase.table('posts').select('*').order('created_at', desc=True).execute()

        # Supabase returns data in response.data
        posts_from_db = response.data
        return jsonify(posts_from_db)

    except Exception as e:
        print(f"Error fetching posts from Supabase: {e}")
        return jsonify({"message": f"Failed to fetch posts: {str(e)}"}), 500

@app.route('/api/posts/<post_id>', methods=['GET']) # <--- ADDED: New endpoint for single post
def get_single_post(post_id):
    """
    Returns a single blog post by its ID from Supabase.
    """
    if not supabase:
        return jsonify({"message": "Supabase client not initialized. Check environment variables."}), 500

    try:
        # Fetch a single post from Supabase by its ID
        response = supabase.table('posts').select('*').eq('id', post_id).limit(1).execute()

        post_data = response.data
        if not post_data:
            return jsonify({"message": "Post not found"}), 404

        return jsonify(post_data[0]) # Return the first (and only) matching post

    except Exception as e:
        print(f"Error fetching single post from Supabase: {e}")
        return jsonify({"message": f"Failed to fetch post: {str(e)}"}), 500


@app.route('/api/upload-image', methods=['POST'])
@auth_required
def upload_image():
    """
    Simulates image upload. In a real application, you would upload the file
    to a cloud storage service (e.g., Firebase Storage, AWS S3, Cloudinary)
    and then return the URL provided by that service.

    Expects FormData with a 'image' file.
    """
    if 'image' not in request.files:
        return jsonify({"message": "No image file provided"}), 400

    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({"message": "No selected file"}), 400

    # This is a placeholder. DO NOT use this for real image storage in production.
    # In a real app, you'd save this to a cloud storage and get a public URL.
    dummy_image_url = f"https://via.placeholder.com/150/0000FF/FFFFFF?text=Image-{datetime.now().timestamp()}"
    print(f"Simulated image upload. Would have uploaded {image_file.filename} to: {dummy_image_url}")

    return jsonify({"message": "Image uploaded successfully (simulated)", "imageUrl": dummy_image_url}), 200

# --- Gemini API Proxy Endpoints ---

@app.route('/api/gemini/<string:model_endpoint>', methods=['POST'])
@auth_required
def gemini_proxy(model_endpoint):
    """
    Proxies requests to the Gemini API based on the model_endpoint.
    e.g., /api/gemini/generateContent, /api/gemini/summarize
    """
    data = request.json
    prompt = data.get("prompt")

    if not prompt:
        return jsonify({"message": "Prompt is required for Gemini API call"}), 400

    if not GEMINI_API_KEY:
        return jsonify({"message": "Gemini API key is not configured on the backend. Please set GEMINI_API_KEY environment variable."}), 500

    gemini_api_method = "generateContent" # Default method for text generation

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:{gemini_api_method}?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }

    try:
        response = requests.post(gemini_url, json=payload)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        gemini_result = response.json()

        generated_text = ""
        if gemini_result.get("candidates") and gemini_result["candidates"][0].get("content") and \
           gemini_result["candidates"][0]["content"].get("parts"):
            generated_text = gemini_result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            print("Gemini API response did not contain expected content:", gemini_result)
            return jsonify({"message": "Gemini API did not return text content.", "details": gemini_result}), 500

        return jsonify({"text": generated_text})

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error calling Gemini API: {e.response.status_code} - {e.response.text}")
        return jsonify({"message": f"Gemini API HTTP Error: {e.response.status_code}", "details": e.response.text}), e.response.status_code
    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error calling Gemini API: {e}")
        return jsonify({"message": "Could not connect to Gemini API. Check network or API key."}), 500
    except requests.exceptions.Timeout as e:
        print(f"Timeout Error calling Gemini API: {e}")
        return jsonify({"message": "Gemini API request timed out."}), 500
    except requests.exceptions.RequestException as e:
        print(f"Error calling Gemini API: {e}")
        return jsonify({"message": f"An error occurred while calling Gemini API: {str(e)}"}), 500
    except Exception as e:
        print(f"Unexpected error in Gemini proxy: {e}")
        return jsonify({"message": f"An unexpected error occurred in Gemini proxy: {str(e)}"}), 500

# --- Server Start ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Flask app running on http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port)
