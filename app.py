from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from functools import wraps

app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key"  # Replace with a secure secret
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://tanmayzade87:OAzDsSFBPvMCuJhL@pra.set7w.mongodb.net/?retryWrites=true&w=majority&appName=PRA"
client = MongoClient(MONGO_URI)
db = client.get_database("mydatabase")
users_collection = db.get_collection("users")
patients_collection = db.get_collection("patients")
counters_collection = db.get_collection("counters")
appointments_collection = db.get_collection("appointments")
medical_history_collection = db.get_collection("medical_history")

# JWT token verification decorator for protected endpoints
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            try:
                token = request.headers["Authorization"].split()[1]
            except IndexError:
                return jsonify({"error": "Token format is invalid"}), 401

        if not token:
            return jsonify({"error": "Token is missing"}), 401

        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            request.user = data  # Store user info in request context
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)
    return decorated

# Improved get_next_medical_history_id function
def get_next_medical_history_id():
    counter = counters_collection.find_one_and_update(
        {'_id': 'medicalHistoryID'},
        {'$inc': {'sequence_value': 1}},
        upsert=True,
        return_document=True
    )

    if 'sequence_value' not in counter:
        counters_collection.update_one({'_id': 'medicalHistoryID'}, {'$set': {'sequence_value': 1000}}, upsert=True)
        return "HIST1000"

    return f"HIST{counter['sequence_value']}"

# Improved book_appointment endpoint
@app.route("/appointment/book", methods=["POST"])
@token_required
def book_appointment():
    data = request.json
    required_fields = ["patientID", "appointmentDate", "reason", "doctor"]
    
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"error": "Missing required appointment fields"}), 400

    try:
        patient_id = int(data["patientID"])
    except ValueError:
        return jsonify({"error": "Invalid patient ID"}), 400

    patient = patients_collection.find_one({"patientID": patient_id})
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    # Use a more robust method to find the next appointment ID
    new_appointment_id = ObjectId()

    appointment_record = {
        "appointmentID": new_appointment_id,
        "patientID": patient_id,
        "appointmentDate": data["appointmentDate"],
        "reason": data["reason"],
        "doctor": data["doctor"],
        "status": "scheduled",
        "createdAt": datetime.datetime.utcnow()
    }

    result = appointments_collection.insert_one(appointment_record)
    
    if result.inserted_id:
        return jsonify({
            "message": "Appointment booked successfully!",
            "appointmentID": str(new_appointment_id)
        }), 201
    else:
        return jsonify({"error": "Failed to book appointment"}), 500

# Improved get_patient_history endpoint
@app.route('/doctor/patient_history/', methods=['GET'])
@token_required
def get_patient_history():
    try:
        patient_id = request.args.get("patientId", type=int)
        if not patient_id:
            return jsonify({"error": "Missing patientId parameter"}), 400
        
        patient = patients_collection.find_one({"patientID": patient_id}, projection={"medicalhistory": 1})
        if not patient:
            return jsonify({"error": "Patient not found"}), 404
        
        medical_history_text = patient.get("medicalhistory", "No medical history available.")

        ai_summaries = medical_history_collection.find({"patientID": patient_id}, sort=[("createdAt", -1)])

        ai_summary_texts = []
        for summary in ai_summaries:
            created_at = summary.get("createdAt", "Unknown date")
            ai_summary_texts.append(f"- AI Summary ({created_at}): {summary.get('ai_summary', 'No details available')}")

        ai_summary_text = "\n".join(ai_summary_texts) if ai_summary_texts else "No previous AI summaries available."

        patient_history = f"""Medical History:
    {medical_history_text}

    Previous AI Summaries:
    {ai_summary_text}"""

        return jsonify({"patient_history": patient_history})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)