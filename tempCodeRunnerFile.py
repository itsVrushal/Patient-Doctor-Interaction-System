import datetime
import jwt  # PyJWT
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient, ReturnDocument
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key"  # Replace with a secure secret
# Allow specific origins (Change according to your frontend URL)
CORS(app)

# MongoDB Connection
MONGO_URI = "mongodb+srv://tanmayzade87:OAzDsSFBPvMCuJhL@pra.set7w.mongodb.net/?retryWrites=true&w=majority&appName=PRA"
client = MongoClient(MONGO_URI)
db = client.get_database("mydatabase")
users_collection = db.get_collection("users")
patients_collection = db.get_collection("patients")
counters_collection = db.get_collection("counters")
appointments_collection = db.get_collection("appointments")
medical_history_collection = db.get_collection("medical_history")  # Added collection

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

def get_next_medical_history_id():
    """
    Generates a sequential numeric Medical History ID (e.g., HIST1001, HIST1002)
    """
    counter = counters_collection.find_one_and_update(
        {'_id': 'medicalHistoryID'},
        {'$inc': {'sequence_value': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    # If sequence_value is not set, initialize at 1000
    if 'sequence_value' not in counter:
        counters_collection.update_one({'_id': 'medicalHistoryID'}, {'$set': {'sequence_value': 1000}}, upsert=True)
        return "HIST1000"

    return f"HIST{counter['sequence_value']}"


@app.route("/doctor/save_medical_history", methods=["POST"])
def save_medical_report():
    data = request.json
    required_fields = ["appointmentId", "patientId", "symptoms", "medications", "reportText", "doctor"]

    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"error": "Missing required medical report fields"}), 400

    try:
        appointment_id = int(data["appointmentId"])
        patient_id = int(data["patientId"])
    except ValueError:
        return jsonify({"error": "Invalid appointmentId or patientId"}), 400

    # Check if the appointment exists
    appointment = appointments_collection.find_one({"appointmentID": appointment_id})
    if not appointment:
        return jsonify({"error": "Appointment not found"}), 404

    # Check if the patient exists
    patient = patients_collection.find_one({"patientID": patient_id})
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    # Generate a unique sequential Medical History ID
    medical_history_id = get_next_medical_history_id()

    # Prepare report data
    report_data = {
        "medicalHistoryID": medical_history_id,
        "appointmentID": appointment_id,
        "patientID": patient_id,
        "symptoms": data["symptoms"],  # Store symptoms as a list
        "medications": data["medications"],  # Store medications as a list
        "reportText": data["reportText"],  # Main diagnosis text
        "doctor": data["doctor"],  # Store doctor's name
        "createdAt": datetime.datetime.utcnow(),
        "ai_summary": data.get("ai_summary", "")  # New attribute (not required, defaults to empty string)
    }

    # Save to the database
    result = medical_history_collection.insert_one(report_data)

    if result.inserted_id:
        return jsonify({
            "message": "Medical report saved successfully!",
            "medicalHistoryID": medical_history_id  # Return the generated ID
        }), 201
    else:
        return jsonify({"error": "Failed to save medical report"}), 500
    





# --- 📌 New Endpoint to Fetch Medical History by Patient ID ---
@app.route('/doctor/medical_history/<int:patient_id>', methods=['GET'])
@token_required
def get_medical_history(patient_id):
    try:
        records = medical_history_collection.find({"patientId": patient_id})
        history_list = []

        for record in records:
            record["_id"] = str(record["_id"])  # Convert ObjectId to string
            history_list.append(record)

        if not history_list:
            return jsonify({"message": "No medical history found for this patient"}), 404

        return jsonify({"medical_history": history_list}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Function to get the next patient ID (sequential numeric, e.g., 1001, 1002, ...)
def get_next_patient_id():
    counter = counters_collection.find_one_and_update(
        {'_id': 'patientid'},
        {'$inc': {'sequence_value': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    # If no previous value existed, initialize to 1000 then increment (result will be 1001)
    if 'sequence_value' not in counter:
        counters_collection.update_one({'_id': 'patientid'}, {'$set': {'sequence_value': 1001}}, upsert=True)
        return 1001
    return counter['sequence_value']





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

    # **Find the last appointmentID and increment it**
    last_appointment = appointments_collection.find_one({}, sort=[("appointmentID", -1)])
    new_appointment_id = (last_appointment["appointmentID"] + 1) if last_appointment else 1

    # **Create appointment record**
    appointment_record = {
        "appointmentID": new_appointment_id,  # Custom sequential ID
        "patientID": patient_id,
        "appointmentDate": data["appointmentDate"],  # ISO-format expected
        "reason": data["reason"],
        "doctor": data["doctor"],  # Doctor name selected from dropdown
        "status": "scheduled",
        "createdAt": datetime.datetime.utcnow()
    }

    # **Insert into MongoDB**
    result = appointments_collection.insert_one(appointment_record)
    
    if result.inserted_id:
        return jsonify({
            "message": "Appointment booked successfully!",
            "appointmentID": new_appointment_id
        }), 201
    else:
        return jsonify({"error": "Failed to book appointment"}), 500
@app.route("/doctor/appointments", methods=["GET"])
@token_required
def doctor_appointments():
    try:
        # Extract the token from the Authorization header
        token_str = request.headers.get("Authorization").split()[1]
        # Decode the token to get the doctor's username
        data = jwt.decode(token_str, app.config["SECRET_KEY"], algorithms=["HS256"])
        doctor_username = data.get("username")
        
        # Find all appointments for this doctor
        appointments_cursor = appointments_collection.find({"doctor": doctor_username})
        appointments = []
        for appt in appointments_cursor:
            # Convert the MongoDB _id to a string
            appt["_id"] = str(appt["_id"])
            # Look up the patient record using the patientID from the appointment
            patient = patients_collection.find_one({"patientID": appt["patientID"]})
            patient_name = (
                f"{patient.get('firstName', '')} {patient.get('lastName', '')}".strip()
                if patient else "Unknown"
            )
            # Append the appointment data, including the custom appointmentID if available
            appointments.append({
                "appointmentID": appt.get("appointmentID", appt["_id"]),
                "patientID": appt["patientID"],
                "patientName": patient_name,
                "appointmentDate": appt["appointmentDate"],
                "reason": appt["reason"],
                "status": appt["status"]
            })
        return jsonify({"appointments": appointments}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch appointments", "details": str(e)}), 500



# New endpoint to retrieve all doctors (users with role "doctor")
@app.route("/doctors", methods=["GET"])
@token_required
def get_doctors():
    try:
        # Find all users where role equals "doctor"
        doctors_cursor = users_collection.find({"role": "doctor"})
        doctors = []
        for doc in doctors_cursor:
            doc["_id"] = str(doc["_id"])
            # Return only relevant fields (e.g., username) - adjust as needed
            doctors.append({
                "username": doc["username"],
                "id": doc["_id"]
            })
        return jsonify({"doctors": doctors}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch doctors", "details": str(e)}), 500

# --- Existing endpoints for signup, login, add_patient, etc. --- #
@app.route("/signup", methods=["POST", "OPTIONS"])
def signup():
    if request.method == "OPTIONS":
        return jsonify({"message": "CORS preflight OK"}), 200

    data = request.json
    required_fields = ["username", "password", "role"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    username = data["username"].lower()
    role = data["role"].lower()
    
    if users_collection.find_one({"username": username}):
        return jsonify({"error": "Username already exists"}), 400

    hashed_password = generate_password_hash(data["password"])
    user_data = {
        "username": username,
        "password": hashed_password,
        "role": role
    }

    users_collection.insert_one(user_data)
    return jsonify({"message": "User registered successfully!"}), 201

@app.route("/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS":
        return jsonify({"message": "CORS preflight OK"}), 200

    data = request.json
    if "username" not in data or "password" not in data:
        return jsonify({"error": "Missing username or password"}), 400

    username = data["username"].lower()
    user = users_collection.find_one({"username": username})

    if user and check_password_hash(user["password"], data["password"]):
        token = jwt.encode({
            "username": username,
            "role": user["role"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }, app.config["SECRET_KEY"], algorithm="HS256")

        return jsonify({
            "message": "Login successful!",
            "role": user["role"],
            "token": token
        }), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route("/nurse/patient", methods=["POST"])
@token_required
def add_patient():
    data = request.json
    required_fields = [
        "firstName", "lastName", "dateOfBirth", "gender", 
        "contactNumber", "bloodType", "address", "emergencyContact"
    ]
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"error": "Missing required patient fields"}), 400

    patient_id = get_next_patient_id()

    patient_record = {
        "patientID": patient_id,
        "firstName": data["firstName"],
        "lastName": data["lastName"],
        "dateOfBirth": data["dateOfBirth"],
        "gender": data["gender"],
        "contactNumber": data["contactNumber"],
        "bloodType": data["bloodType"],
        "address": data["address"],
        "emergencyContact": data["emergencyContact"],
        "medicalhistory": data.get("medicalhistory", ""),
        "currentMedications": data.get("currentMedications", ""),
        "icuAdmitted": bool(data.get("icuAdmitted", False)),
        "createdAt": datetime.datetime.utcnow()
    }

    result = patients_collection.insert_one(patient_record)
    if result.inserted_id:
        return jsonify({
            "message": "Patient added successfully!",
            "patientID": patient_id
        }), 201
    else:
        return jsonify({"error": "Failed to add patient"}), 500

@app.route("/nurse/patient_list", methods=["GET"])
@token_required
def get_patient_list():
    try:
        patients_cursor = patients_collection.find()
        patients = []
        for patient in patients_cursor:
            patient["_id"] = str(patient["_id"])
            patients.append(patient)
        return jsonify({"patients": patients}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch patient list", "details": str(e)}), 500

@app.route("/doctor/patient_list", methods=["GET"])
def doctor_patient_list():
    patients_cursor = patients_collection.find()
    patients = []
    for patient in patients_cursor:
        patient["_id"] = str(patient["_id"])
        patients.append(patient)
    return jsonify({"patients": patients}), 200

@app.route("/doctor/patient/<patient_id>", methods=["GET"])
def get_patient_details(patient_id):
    try:
        patient = patients_collection.find_one({"_id": ObjectId(patient_id)})
        if not patient:
            return jsonify({"error": "Patient not found"}), 404
        patient["_id"] = str(patient["_id"])
        return jsonify({"patient": patient}), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch patient details", "details": str(e)}), 500

@app.route("/nurse/patient_by_contact", methods=["GET"])
@token_required
def get_patient_by_contact():
    contact_number = request.args.get("contactNumber")
    if not contact_number:
        return jsonify({"error": "Missing contact number"}), 400
    patient = patients_collection.find_one({"contactNumber": contact_number})
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    patient["_id"] = str(patient["_id"])
    return jsonify({"patient": patient}), 200

# OPTIONS handler for /doctor/reportdata to support CORS preflight requests
@app.route("/doctor/reportdata", methods=["OPTIONS"])
def reportdata_options():
    return "", 200

# Endpoint to retrieve report data based on appointmentID
@app.route("/doctor/reportdata", methods=["GET", "OPTIONS"])
@token_required
def get_report_data():
    if request.method == "OPTIONS":
        return "", 200

    appointment_id = request.args.get("appointmentId")
    if not appointment_id:
        return jsonify({"error": "Missing appointmentId parameter"}), 400

    try:
        # Since we're using a custom appointmentID (stored as an integer), convert the parameter to int.
        appointment = appointments_collection.find_one({"appointmentID": int(appointment_id)})
    except Exception as e:
        return jsonify({"error": "Error processing appointmentId", "details": str(e)}), 400

    if not appointment:
        return jsonify({"error": "Appointment not found"}), 404

    # Retrieve the patient using the patientID from the appointment
    patient = patients_collection.find_one({"patientID": appointment["patientID"]})
    if not patient:
        return jsonify({"error": "Patient not found"}), 404



    report_data = {
        "appointmentID": appointment.get("appointmentID"),
        "patientName": f"{patient.get('firstName', '')} {patient.get('lastName', '')}".strip(),
        "gender": patient.get("gender", "Unknown"),
        "bloodGroup": patient.get("bloodType", "Unknown"),
        "patientID": patient.get("patientID"),
        "contactNumber": patient.get("contactNumber", "Unknown"),
        "appointmentDateTime": appointment.get("appointmentDate")
    }

    return jsonify(report_data), 200

# create new function where it will return patient history text to doctor_patient_report.html it  will return string
# mongodb -> present history(during adding patient)incuding allergy, previous ai report summary(if present)
# output -> a string to html page
@app.route("/doctor/patient_history/", methods=["GET"])
# @token_required
def get_patient_history():
    try:
        patient_id = request.args.get("patientId", type=int)  # Extract from query params
        if not patient_id:
            return jsonify({"error": "Missing patientId parameter"}), 400
        
        # Find patient's medical history from `patients_collection`
        patient = patients_collection.find_one({"patientID": patient_id})
        if not patient:
            return "No patient record found."

        medical_history_text = patient.get("medicalhistory", "No medical history available.")

        # Fetch previous AI summaries from `medical_history_collection`
        ai_summaries = medical_history_collection.find({"patientID": patient_id}, sort=[("createdAt", -1)])

        ai_summary_texts = []
        for summary in ai_summaries:
            created_at = summary.get("createdAt", "Unknown date")
            ai_summary_texts.append(f"- AI Summary ({created_at}): {summary.get('ai_summary', 'No details available')}")

        ai_summary_text = "\n".join(ai_summary_texts) if ai_summary_texts else "No previous AI summaries available."

        # Format final response
        patient_history = f"""Medical History:
    {medical_history_text}

    Previous AI Summaries:
    {ai_summary_text}"""

        return patient_history

    except Exception as e:
        return f"Error retrieving patient history: {str(e)}"


# create new function if specific button is clicked , then it will take input array of medication and symptom and medical history of patient and convert them into three strings and will return text to doctor_patient_report js
# mongodb -> present history(during adding patient)incuding allergy, previous ai report summary(if present), symptoms string , medication string(by doctor)   (need data in string instead of array)
#output -> a string to html page
#we can also include additional notes
@app.route('/analyze', methods=['POST'])
def analyze_patient():
    try:
        data = request.json  # Get JSON data from request
        
        # Extract data
        patient_id = data.get('patientID')
        appointment_id = data.get('appointmentID')
        symptoms = data.get('symptoms', '')
        medications = data.get('medications', '')

        # Validate data
        if not patient_id or not appointment_id:
            return jsonify({"error": "Missing Patient ID or Appointment ID"}), 400

        if not symptoms and not medications:
            return jsonify({"error": "No symptoms or medications provided"}), 400

        # Mock AI processing (Replace this with actual AI model logic)
        analysis = f"Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.  Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation.Based on symptoms ({symptoms}) and medications ({medications}), AI suggests further evaluation."

        # Return JSON response
        return jsonify({"analysis": analysis})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# current bugs report is submitting automatically
# output data is not well structured for both ai analysis
if __name__ == "__main__":
    app.run(debug=True)
