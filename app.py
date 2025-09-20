# app.py

from flask import Flask, render_template, request, jsonify
from auth.auth_service import verify_user_credentials

app = Flask(__name__)

@app.route('/')
def home():
    """Renders the login page."""
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    """Handles the login form submission."""
    email = request.form.get('email')
    password = request.form.get('password')
    
    is_successful, message = verify_user_credentials(email, password)
    
    if is_successful:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 401 # Unauthorized

if __name__ == '__main__':
    app.run(debug=True)