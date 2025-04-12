from email.mime.text import MIMEText
import smtplib
from flask import Flask, flash, request, render_template, redirect, session, url_for
from bson import ObjectId
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from datetime import datetime


app = Flask(__name__)
app.secret_key = 'supersecretkey'

# MongoDB setup
client = MongoClient("mongodb+srv://neuroheatlthtech:OesOWSpYAMHhDM2r@cluster0.ve2gvcl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client['smart_healthcare_db']
hospitals_collection = db['hospitals']
doctors_collection = db['doctors']
users_collection = db['users']
medical_history_collection = db['medical_history']
appointments_collection = db['appointments']
prescriptions = db['prescriptions']
reminders_collection = db['reminders']

def send_email(to_email, subject, body):
    sender = "neuroheatlthtech@gmail.com"
    password = "rjnzwuffznddgdms"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to_email, msg.as_string())

# Suggest a replacement doctor based on specialization
def suggest_replacement_doctor(original_doctor_id):
    original = db.doctors.find_one({"_id": ObjectId(original_doctor_id)})
    if not original: return None
    return db.doctors.find_one({
        "specialization": original["specialization"],
        "on_leave": False,
        "_id": {"$ne": original["_id"]}
    })

# Endpoint to handle emergency leave
@app.route('/handle-emergency-leave-consent', methods=['POST'])
def handle_emergency_leave_consent():
    doctor_id = request.form.get("doctor_id")
    doctor = db.doctors.find_one({"_id": ObjectId(doctor_id)})
    if not doctor:
        flash("Doctor not found!", "error")
        return redirect("/dashboard")

    today = datetime.today().strftime("%Y-%m-%d")
    appointments = db.appointments.find({
        "doctor_id": ObjectId(doctor_id),
        "appointment_date": {"$gte": today},
        "status": "confirmed"
    })

    for appt in appointments:
        replacement = suggest_replacement_doctor(doctor_id)
        if not replacement: continue

        consent_token = str(ObjectId())
        db.appointment_consent.insert_one({
            "appointment_id": appt["_id"],
            "patient_email": appt["patient_email"],
            "old_doctor": doctor["name"],
            "new_doctor": replacement["name"],
            "replacement_id": replacement["_id"],
            "consent_token": consent_token,
            "status": "pending"
        })

        send_email(
            appt["patient_email"],
            "Doctor Unavailable - Reassignment Consent Needed",
            f"""
Hello,

Your appointment with Dr. {doctor['name']} needs to be reassigned due to an emergency.

We recommend Dr. {replacement['name']} as an alternative.

To confirm or reject the reassignment, click below:

✅ Accept: http://yourdomain.com/consent?token={consent_token}&action=accept  
❌ Reject: http://yourdomain.com/consent?token={consent_token}&action=reject

Thank you,  
SmartHealthAI Team
"""
        )

    flash("Patients have been notified for doctor reassignment.", "success")
    return redirect("/dashboard")

# Endpoint to handle patient consent
@app.route('/consent')
def handle_consent_response():
    token = request.args.get("token")
    action = request.args.get("action")
    consent = db.appointment_consent.find_one({"consent_token": token})
    if not consent:
        return "Invalid or expired link."

    if action == "accept":
        db.appointments.update_one(
            {"_id": consent["appointment_id"]},
            {"$set": {"doctor_id": consent["replacement_id"]}}
        )
        db.appointment_consent.update_one(
            {"_id": consent["_id"]},
            {"$set": {"status": "accepted"}}
        )
        return "✅ Thank you! Your appointment has been reassigned."

    elif action == "reject":
        db.appointment_consent.update_one(
            {"_id": consent["_id"]},
            {"$set": {"status": "rejected"}}
        )
        return "❌ You have rejected the reassignment. We'll contact you shortly."

    return "Invalid action."

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email').lower()
        password = request.form.get('password')
        role = request.form.get('role')

        if not name or not email or not password or not role:
            flash("All fields are required.", "error")
            return redirect(url_for('register'))

        if users_collection.find_one({"email": email}):
            flash("Email already registered.", "error")
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        user_id = users_collection.insert_one({
            "name": name,
            "email": email,
            "password": hashed_password,
            "role": role
        }).inserted_id

        session['user_id'] = str(user_id)
        session['user_name'] = name
        session['user_role'] = role

        flash("Registration successful!", "success")
        return redirect(url_for('add_hospital') if role == 'admin' else url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role")

        print(f"Login attempt - Email: {email}, Role: {role}")

        if role == "doctor":
            doctor = doctors_collection.find_one({"email": email})
            print("Doctor found:", doctor)

            if doctor and check_password_hash(doctor["password"], password):
                session["user_id"] = str(doctor["_id"])
                session["role"] = "doctor"
                flash("Doctor login successful!", "success")
                return redirect("/doctor_dashboard")
            else:
                flash("Invalid credentials for doctor.", "error")
                return redirect("/login")
        print(f"Attempting to login with email: {email}, role: {role}")

        user = users_collection.find_one({"email": email, "role": role})
        if user:
            print(f"User found: {user['name']}")
            if check_password_hash(user['password'], password):
                session['user_id'] = str(user['_id'])
                session['user_name'] = user['name']
                session['user_role'] = user['role']
                flash(f"Welcome back, {user['name']}!", "success")
                return redirect(url_for(f'{role}_dashboard'))
            else:
                flash("Invalid password.", "error")
        else:
            flash("No user found with this email and role.", "error")

    return render_template('login.html')


@app.route('/doctor_dashboard', methods=['GET', 'POST'])
def doctor_dashboard():
    if 'user_id' not in session or session.get('role') != 'doctor':
        flash("Access denied.", "error")
        return redirect(url_for('login'))

    doctor_id = ObjectId(session['user_id'])
    doctor = doctors_collection.find_one({"_id": doctor_id})

    if not doctor:
        flash("Doctor not found.", "error")
        return redirect(url_for('login'))

    # Doctor details
    doctor_name = doctor.get("name", "Dr. Unknown")
    doctor_specialization = doctor.get("specialization", "Not specified")
    doctor_experience = doctor.get("experience", "Not specified")
    doctor_availability = doctor.get("availability", "Available")

    # Fetch upcoming appointments for the doctor
    today = datetime.now().strftime('%Y-%m-%d')
    upcoming_appointments = list(appointments_collection.find({
        "doctor_id": doctor_id,
        "date": {"$gte": today},
        "status": "upcoming"
    }))

    # Retrieve patient names for each appointment
    for appointment in upcoming_appointments:
        patient_id = appointment.get("patient_id")
        if patient_id:
            patient = users_collection.find_one({"_id": patient_id})
            appointment["patient_name"] = patient.get("name", "Unknown")

    # Check for leave status
    doctor_on_leave = doctor.get("leave_status", False)

    if request.method == 'POST':
        # Toggle leave status
        leave_status = request.form.get("leave", False)
        doctors_collection.update_one(
            {"_id": doctor_id},
            {"$set": {"leave_status": leave_status}}
        )
        flash("Leave status updated.", "success")
        return redirect(url_for('doctor_dashboard'))

    return render_template(
        'doctor_dashboard.html',
        doctor_name=doctor_name,
        doctor_specialization=doctor_specialization,
        doctor_experience=doctor_experience,
        doctor_availability=doctor_availability,
        upcoming_appointments=upcoming_appointments,
        doctor_on_leave=doctor_on_leave
    )

@app.route('/add_prescription/<patient_id>', methods=['GET', 'POST'])
def add_prescription(patient_id):
    # Find the patient based on patient_id
    patient = users_collection.find_one({'_id': ObjectId(patient_id)})
    
    if patient is None:
        return "Patient not found", 404

    # On POST request, save the prescription to the database
    if request.method == 'POST':
        medication = request.form.get('medication')
        dosage = request.form.get('dosage')
        frequency = request.form.get('frequency')
        duration = request.form.get('duration')

        # Create a prescription document
        prescription = {
            'patient_id': ObjectId(patient_id),
            'medication': medication,
            'dosage': dosage,
            'frequency': frequency,
            'duration': duration,
            'date': datetime.utcnow()  # Correct datetime usage
        }

        # Insert prescription into database
        prescriptions.insert_one(prescription)

        return redirect(url_for('doctor_dashboard'))

    # If GET request, render the prescription form
    return render_template("add_prescription.html", patient_name=patient['name'])




@app.route('/add_hospital', methods=['GET', 'POST'])
def add_hospital():
    if 'user_id' not in session or session.get('user_role') != 'admin':
        flash("Only admins can register hospitals.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        hospital = {
            "name": request.form['hospital_name'],
            "address": request.form['hospital_address'],
            "admin_id": ObjectId(session['user_id'])
        }
        hospital_id = hospitals_collection.insert_one(hospital).inserted_id
        session['hospital_id'] = str(hospital_id)
        flash("Hospital registered successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    return render_template('add_hospital1.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'admin':
        flash("Access denied.", "error")
        return redirect(url_for('login'))

    hospital = hospitals_collection.find_one({"admin_id": ObjectId(session['user_id'])})
    if not hospital:
        flash("Please register your hospital first.", "error")
        return redirect(url_for('add_hospital'))

    # ✅ Make sure hospital_id is set in session
    session['hospital_id'] = str(hospital['_id'])

    doctors = list(doctors_collection.find({"hospital_id": hospital['_id']}))
    return render_template('admin_dashboard.html', hospital=hospital, doctors=doctors)

@app.route('/add-doctor', methods=['GET', 'POST'])
def add_doctor():
    if 'hospital_id' not in session:
        flash("Hospital ID missing. Please re-login.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':

        doctor_data = {
    'name': request.form['name'],
    'specialization': request.form['specialization'],
    'email': request.form['email'],
    'phone': request.form['phone'],
    'password': generate_password_hash(request.form['password']),  # Corrected this line
    'available_days': request.form.getlist('available_days'),
    'available_from': request.form['available_from'],
    'available_to': request.form['available_to'],
    'hospital_id': ObjectId(session['hospital_id']),  # Assuming you are using MongoDB
    'on_leave': False,
    'experience': int(request.form.get('experience', 0)),
    'current_appointments': 0,
    'max_capacity': 10,
    'reviews': []
}

        doctors_collection.insert_one(doctor_data)
        flash('Doctor added successfully!')
        return redirect(url_for('admin_dashboard'))

    return render_template('add_doctor1.html')
@app.route('/toggle_leave/<doctor_id>')
def toggle_leave(doctor_id):
    if 'user_id' not in session or session.get('user_role') != 'admin':
        flash("Unauthorized action.", "error")
        return redirect(url_for('login'))

    doctor = doctors_collection.find_one({"_id": ObjectId(doctor_id)})
    if doctor:
        new_status = not doctor.get("on_leave", False)
        doctors_collection.update_one({"_id": doctor["_id"]}, {"$set": {"on_leave": new_status}})
        flash("Doctor leave status updated.", "success")

    return redirect(url_for('admin_dashboard'))

@app.route('/patient_dashboard')
def patient_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'patient':
        flash("Access denied.", "error")
        return redirect(url_for('login'))

    patient_id = ObjectId(session['user_id'])
    today = datetime.now().strftime('%Y-%m-%d')

    # Fetch the patient's details, medical history, upcoming appointments, prescriptions, and reminders
    patient_data = users_collection.find_one({'_id': patient_id})
    
    # Fetch prescriptions and avoid the name conflict by renaming the query variable
    patient_prescriptions = list(prescriptions.find({'patient_id': patient_id}))
    for prescription in patient_prescriptions:
        # Add the doctor's name to each prescription (assuming it's stored in the 'doctor_name' field)
        prescription['doctor_name'] = prescription.get('doctor_name', 'Unknown Doctor')
    
    upcoming_appointments = list(appointments_collection.find({
        'patient_id': patient_id,
        'date': {'$gte': today}
    }))

    return render_template(
        'patient_dashboard.html',
        patient=patient_data,
        medical_history=list(medical_history_collection.find({'patient_id': patient_id})),
        upcoming_appointments=upcoming_appointments,
        prescriptions=patient_prescriptions,  # Updated variable name
        reminders=list(reminders_collection.find({'patient_id': patient_id}))
    )

@app.route('/report-symptoms')
def report_symptoms():
    return render_template('symptoms.html')

from flask import request, render_template
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

@app.route('/submit-symptoms', methods=['POST'])
def submit_symptoms():
    symptoms = request.form['symptoms']
    duration = int(request.form['duration'])
    severity = request.form['severity']

    # ✅ Step 1: Improved Symptom-to-specialization matching
    symptom_map = {
        "fever": "General Physician",
        "headache": "Neurologist",
        "nausea": "Gastroenterologist",
        "chest pain": "Cardiologist",
        "skin rash": "Dermatologist",
        "cough": "Pulmonologist",
        "cold": "General Physician",
        "dizziness": "Neurologist",
        "shortness of breath": "Pulmonologist",
        "hearing": "ENT"
        
    }

    matched_specializations = set()
    for key, specialization in symptom_map.items():
        if key in symptoms.lower():
            matched_specializations.add(specialization)

    if not matched_specializations:
        matched_specializations = {"General Physician"}

    # Step 2: Query doctors from DB
    matched_doctors = list(doctors_collection.find({
        "specialization": {"$in": list(matched_specializations)},
        "on_leave": False
    }))

    if not matched_doctors:
        return render_template("no_doctors.html", symptoms=symptoms)

    # Step 3: Scoring
    def doctor_score(doc):
        reviews = doc.get('reviews', [])
        review_text = ' '.join([r.get('comment', '') for r in reviews]).lower() if reviews else "no reviews"

        vectorizer = TfidfVectorizer(stop_words='english')
        tfidf = vectorizer.fit_transform([symptoms.lower(), review_text])
        similarity = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]

        experience = doc.get('experience', 0) / 10.0
        load = 1.0 - min(doc.get('current_appointments', 0) / 10.0, 1.0)

        return 0.5 * similarity + 0.3 * experience + 0.2 * load

    ranked_doctors = sorted(matched_doctors, key=doctor_score, reverse=True)
    top_doctors = ranked_doctors[:3]

    # Step 4: Format data for frontend
    suggested_doctors = []
    for doc in top_doctors:
        suggested_doctors.append({
            "id": str(doc["_id"]),
            "name": doc["name"],
            "specialization": doc["specialization"],
            "timings": f'{doc["available_from"]} - {doc["available_to"]} on {", ".join(doc["available_days"])}',
            "hospital": str(doc["hospital_id"])  # You can query hospital name here if needed
        })

    return render_template(
        'doctor_recommendation.html',
        suggested_doctors=suggested_doctors,
        symptoms_entered=symptoms
    )

@app.route('/book/<doctor_id>', methods=['POST'])
def book_appointment(doctor_id):
    if 'user_id' not in session or session.get('user_role') != 'patient':
        flash("Please login as a patient to book an appointment.", "error")
        return redirect(url_for('login'))

    appointment_date = request.form['date']
    appointment = {
        'doctor_id': ObjectId(doctor_id),
        'patient_id': ObjectId(session['user_id']),
        'date': appointment_date,
        'status': 'upcoming',
        'created_at': datetime.now()
    }

    appointments_collection.insert_one(appointment)

    # Update doctor's appointment count
    doctors_collection.update_one(
        {'_id': ObjectId(doctor_id)},
        {'$inc': {'current_appointments': 1}}
    )

    flash("Appointment booked successfully!", "success")
    return redirect(url_for('patient_dashboard'))

@app.route('/generate_prescription/<int:patient_id>', methods=['GET', 'POST'])
def generate_prescription(patient_id):
    if request.method == 'POST':
        medication = request.form['medication']
        dosage = request.form['dosage']
        duration = request.form['duration']
        additional_notes = request.form['additional_notes']
        
        # Logic to save the prescription data, possibly in a database
        # Example: save_prescription(patient_id, medication, dosage, duration, additional_notes)
        
        # Redirect or render a confirmation page
        return redirect(url_for('prescription_confirmation', patient_id=patient_id))
    
    # Fetch patient details from the database using patient_id
    patient = users_collection(patient_id)
    
    return render_template('prescription.html', patient_name=patient['name'], patient_age=patient['age'], patient_gender=patient['gender'], patient_diagnosis=patient['diagnosis'], patient_id=patient_id)



@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)