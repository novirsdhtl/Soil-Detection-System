# import library
from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response, g, send_file, Response
from functools import wraps
from werkzeug.utils import secure_filename
from flask_mysqldb import MySQL
import os
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import img_to_array, load_img
import re
import io
import base64
from PIL import Image

app = Flask(__name__)
app.secret_key = 'soil_app_secret_key'

# configure mysql database
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_PORT'] = 3307
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'deteksitanah'
mysql = MySQL(app)

app.config['UPLOAD_FOLDER'] = 'static/uploads'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_filename(filename):
    filename = filename.replace(" ", "_")
    filename = re.sub(r'[^\w\s.-]', '', filename)
    return filename

# Load model
# Path ke direktori model SavedModel
saved_model_dir = r'D:\Riset\Soil_App\model'

# Muat model
model = tf.saved_model.load(saved_model_dir)
infer = model.signatures['serving_default']

def preprocess_image(image_path):
    img = Image.open(image_path)
    img = img.resize((240, 240))  # Sesuaikan dengan ukuran input model
    img_array = np.array(img)
    img_array = img_array.astype(np.float32) / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    return img_array

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'id_user' not in session and 'id_admin' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def add_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# app routing
@app.route('/')
def index():
    return render_template('index.html')

# user-routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    error=None
    if request.method == "POST":
        username=request.form['username']
        password=request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM `user` WHERE `username`='"+username+"' AND `password`='"+password+"'")
        data=cur.fetchone()
        if data is None:
            error = "Data are not available or invalid"
            return render_template('login.html', error=error)
        else:
            session['id_user'] = data[0]
            return redirect(url_for('dashboard'))
    else:
        return render_template('login.html')
    
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == "POST":
        username=request.form['username']
        password=request.form['password']
        fullname=request.form['fullname']
        email=request.form['email']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO `user`(`username`, `password`, `fullname`, `email`) VALUES (%s,%s,%s,%s)", (username,password,fullname,email))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('login'))
    else:
        return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    response = make_response(render_template('dashboard.html', active_page='dashboard'))
    return add_cache_headers(response)

@app.route('/deteksi', methods=['GET', 'POST'])
@login_required
def deteksi():
    try:
        if request.method == 'POST':
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)

            file = request.files['file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)

            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)

                if 'id_user' in session:
                    id_user = session['id_user']
                    cur = mysql.connection.cursor()
                    cur.execute("INSERT INTO `unggah_gambar` (`nama_gambar`, `gambar`, `id_user`) VALUES (%s, %s, %s)", 
                                (filename, file_path, id_user))
                    mysql.connection.commit()
                    id_gambar = cur.lastrowid
                    cur.close()
                    session['last_image_id'] = id_gambar
                    return redirect(url_for('prediksi', id_gambar=id_gambar))

                elif 'id_admin' in session:
                    id_admin = session['id_admin']
                    cur = mysql.connection.cursor()
                    cur.execute("INSERT INTO `unggah_gambar` (`nama_gambar`, `gambar`, `id_admin`) VALUES (%s, %s, %s)", 
                                (filename, file_path, id_admin))
                    mysql.connection.commit()
                    id_gambar = cur.lastrowid
                    cur.close()
                    session['last_image_id'] = id_gambar
                    return redirect(url_for('admin_prediksi', id_gambar=id_gambar))

            else:
                flash('File type not allowed. Allowed types are png, jpg, jpeg.')
                return redirect(request.url)

        else:
            if 'id_user' in session:
                response = make_response(render_template('deteksi.html', active_page='deteksi'))
            elif 'id_admin' in session:
                response = make_response(render_template('admin_deteksi.html', active_page='deteksi'))
            return add_cache_headers(response)

    except Exception as e:
        flash(f'An error occurred: {str(e)}')
        return redirect(url_for('deteksi'))

@app.route('/prediksi/<int:id_gambar>')
def prediksi(id_gambar):
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT `gambar` FROM `unggah_gambar` WHERE `id_gambar` = %s", (id_gambar,))
        result = cur.fetchone()
        cur.close()

        if result:
            file_path = result[0]
            file_path = file_path.replace(b'\\', b'/').decode('utf-8')
            filename = os.path.basename(file_path)
            
            # Proses gambar dan prediksi
            img_array = preprocess_image(file_path)
            prediction = infer(tf.convert_to_tensor(img_array))

            # Menentukan kelas yang diprediksi
            label_dict = {0: 'Alluvial', 1: 'Grumusol', 2: 'Latosol', 3: 'Litosol', 4: 'Mediteran', 5: 'Organosol', 6: 'Rendzina'}
            predicted_class = np.argmax(prediction['sequential_3'].numpy())
            predicted_label = label_dict.get(predicted_class, 'Unknown')
            predicted_percentage = prediction['sequential_3'].numpy()[0][predicted_class] * 100
            
            # Simpan hasil prediksi ke database
            cur = mysql.connection.cursor()
            cur.execute("UPDATE `unggah_gambar` SET `predicted_label` = %s WHERE `id_gambar` = %s", (predicted_label, id_gambar))
            mysql.connection.commit()
            cur.close()

            # URL gambar yang dipilih
            selected_image_url = url_for('static', filename='uploads/' + filename)

            # Render hasil prediksi
            response = make_response(render_template('prediksi.html', selected_image_url=selected_image_url, result=predicted_label, percentage=predicted_percentage, active_page= 'deteksi'))
            return response
        else:
            flash('Image not found.')
            return redirect(url_for('deteksi'))
    except Exception as e:
        flash(f'An error occurred: {str(e)}')
        return redirect(url_for('deteksi'))

@app.route('/tanaman')
@login_required
def tanaman():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT nama_tanaman, deskripsi, gambar_tanaman FROM tanaman")
        tanamans = cur.fetchall()
        cur.close()
        response = make_response(render_template('rekomendasi.html', tanamans=tanamans, active_page='deteksi'))
        return add_cache_headers(response)
    except Exception as e:
        flash(f'An error occurred: {str(e)}')
        return redirect(url_for('deteksi'))
    
@app.route('/profil')
@login_required
def profil():
    if 'id_user' in session:
        id_user = session['id_user']
        cur = mysql.connection.cursor()
        query = "SELECT `fullname`, `username`, `email` FROM `user` WHERE `id_user` = %s"
        cur.execute(query, (id_user,))
        user_data = cur.fetchone()
        cur.close()

        if user_data:
            # Mapping the database result to match HTML template structure
            user = {
                'nama_lengkap': user_data[0],
                'username': user_data[1],
                'email': user_data[2]
            }
            return render_template('profil.html', active_page='profil', user=user)
        else:
            flash('User tidak ditemukan.', 'danger')
            return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('login'))

@app.route('/edit_profil_user', methods=['GET', 'POST'])
@login_required
def edit_profil_user():
    if 'id_user' in session:
        id_user = session['id_user']
        cur = mysql.connection.cursor()
        if request.method == 'GET':
            query = "SELECT `fullname`, `username`, `email` FROM `user` WHERE `id_user` = %s"
            cur.execute(query, (id_user,))
            user_data = cur.fetchone()
            cur.close()

            if user_data:
                user = {
                    'nama_lengkap': user_data[0],
                    'username': user_data[1],
                    'email': user_data[2]
                }
                return render_template('edit_profil.html', user=user, active_page='profil')
            else:
                flash('User tidak ditemukan.', 'danger')
                return redirect(url_for('dashboard'))

        if request.method == 'POST':
            new_fullname = request.form['nama_lengkap']
            new_username = request.form['username']
            new_email = request.form['email']

            query = "UPDATE `user` SET `fullname` = %s, `username` = %s, `email` = %s WHERE `id_user` = %s"
            cur.execute(query, (new_fullname, new_username, new_email, id_user))
            mysql.connection.commit()
            cur.close()

            flash('Profil berhasil diperbarui!', 'success')
            return redirect(url_for('profil'))
    else:
        return redirect(url_for('login'))

@app.route('/varian_tanah')
@login_required
def varian_tanah():
    cur = mysql.connection.cursor()
    cur.execute("SELECT id_tanah, jenis_tanah, deskripsi, gambar_tanah FROM tanah")
    tanah_list = cur.fetchall()
    cur.close()
    tanah_list_encoded = []
    for tanah in tanah_list:
        id_tanah, jenis_tanah, deskripsi, gambar_tanah = tanah
        if gambar_tanah:
            gambar_tanah_encoded = base64.b64encode(gambar_tanah).decode('utf-8')
        else:
            gambar_tanah_encoded = None
        tanah_list_encoded.append((id_tanah, jenis_tanah, deskripsi, gambar_tanah_encoded))
    
    return render_template('varian_tanah.html', tanah_list=tanah_list_encoded, active_page='varian_tanah')

    
#admin-routes
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM `admin` WHERE `username`=%s AND `password`=%s", (username, password))
        data = cur.fetchone()
        cur.close()
        if data is None:
            error = "Invalid admin credentials"
            return render_template('admin_login.html', error=error)
        else:
            session['id_admin'] = data[0]
            session['role'] = 'admin'
            return redirect(url_for('admin_dashboard'))
    else:
        return render_template('admin_login.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'id_admin' in session:
        return render_template('admin_dashboard.html', active_page='admin_dashboard')
    else:
        return redirect(url_for('admin_login'))

# routes new
@app.route('/lihat_variantanah')
@login_required
def lihat_variantanah():
    cur = mysql.connection.cursor()
    cur.execute("SELECT id_tanah, jenis_tanah, deskripsi, gambar_tanah FROM tanah")
    tanah_data = cur.fetchall()

    # Convert BLOB data to Base64 for display
    tanah_list = []
    for tanah in tanah_data:
        if tanah[3]:  # Check if gambar_tanah exists
            gambar_base64 = base64.b64encode(tanah[3]).decode('utf-8')
        else:
            gambar_base64 = None
        tanah_list.append((tanah[0], tanah[1], tanah[2], gambar_base64))

    cur.close()
    return render_template('lihat_variantanah.html', tanah=tanah_list, active_page='lihat_variantanah')

# Route to add new soil variant
@app.route('/tambah_variantanah', methods=['GET', 'POST'])
def tambah_variantanah():
    if request.method == 'POST':
        jenis_tanah = request.form['jenis_tanah']
        deskripsi = request.form['deskripsi']
        
        # Handling the uploaded image
        gambar_tanah = None
        if 'gambar_tanah' in request.files:
            gambar_file = request.files['gambar_tanah']
            if gambar_file:
                gambar_tanah = gambar_file.read()

        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO tanah (jenis_tanah, deskripsi, gambar_tanah) VALUES (%s, %s, %s)", (jenis_tanah, deskripsi, gambar_tanah))
        mysql.connection.commit()
        cur.close()

        flash('Variant Tanah berhasil ditambahkan')
        return redirect(url_for('lihat_variantanah'))
    return render_template('tambah_variantanah.html', active_page='lihat_variantanah')

@app.route('/edit_variantanah/<int:id_tanah>', methods=['GET', 'POST'])
def edit_variantanah(id_tanah):
    cur = mysql.connection.cursor()
    
    if request.method == 'POST':
        jenis_tanah = request.form.get('jenis_tanah')
        deskripsi = request.form.get('deskripsi')
        
        # Handling image update
        gambar_tanah = None
        if 'gambar_tanah' in request.files:
            gambar_file = request.files['gambar_tanah']
            if gambar_file and gambar_file.filename:
                gambar_tanah = gambar_file.read()
        
        if gambar_tanah:
            cur.execute("UPDATE tanah SET jenis_tanah = %s, deskripsi = %s, gambar_tanah = %s WHERE id_tanah = %s",
                        (jenis_tanah, deskripsi, gambar_tanah, id_tanah))
        else:
            cur.execute("UPDATE tanah SET jenis_tanah = %s, deskripsi = %s WHERE id_tanah = %s",
                        (jenis_tanah, deskripsi, id_tanah))
        
        mysql.connection.commit()
        cur.close()
        flash('Data tanah berhasil diupdate!')
        return redirect(url_for('lihat_variantanah'))

    cur.execute("SELECT * FROM tanah WHERE id_tanah = %s", (id_tanah,))
    variant = cur.fetchone()
    cur.close()

    if not variant:
        flash('Varian tanah tidak ditemukan.')
        return redirect(url_for('lihat_variantanah'))
        
    return render_template('edit_variantanah.html', variant=variant, active_page='lihat_variantanah')


# Route to delete soil variant
@app.route('/hapus_variantanah/<int:id_tanah>')
def hapus_variantanah(id_tanah):
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM tanah WHERE id_tanah = %s", (id_tanah,))
    mysql.connection.commit()
    cur.close()
    
    flash('Variant Tanah berhasil dihapus')
    return redirect(url_for('lihat_variantanah'))

    
@app.route('/logout')
def logout():
    session.pop('id_user', None)
    session.pop('id_admin', None)
    response = redirect(url_for('index'))
    response = add_cache_headers(response)
    return response



if __name__ == '__main__':
    app.run(debug=True)