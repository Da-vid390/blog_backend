from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

# Dummy user (you can later store this in a JSON file or DB)
users = {
    "macaulaydavid88@gmail.com": {
        "password": "password123",
        "id": "user-001"
    }
}

# In-memory blog posts
posts = []

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = users.get(email)
    if user and user["password"] == password:
        return jsonify({"success": True, "user_id": user["id"]})
    return jsonify({"success": False, "error": "Invalid credentials"}), 401

@app.route('/post', methods=['POST'])
def create_post():
    data = request.json
    required = ["title", "content", "author_id"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing data"}), 400

    post = {
        "title": data["title"],
        "content": data["content"],
        "author_id": data["author_id"],
        "created_at": datetime.now().isoformat()
    }
    posts.append(post)
    return jsonify({"success": True, "post": post})

@app.route('/posts', methods=['GET'])
def get_posts():
    return jsonify({"posts": posts})

if __name__ == '__main__':
    import os
port = int(os.environ.get("PORT", 5000))
app.run(host='0.0.0.0', port=port)
