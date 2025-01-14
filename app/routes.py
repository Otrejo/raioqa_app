from flask import Blueprint, render_template, request, jsonify, url_for
from .models import UploadedFile
from . import db
import os
import glob
import matplotlib
matplotlib.use('Agg')
import pydicom
import numpy as np
from PIL import Image
from pylinac import WinstonLutz

main = Blueprint('main', __name__)

UPLOAD_FOLDER = 'app/static/images/files_saved_here'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Route to clear the 'files_saved_here' directory
@main.route('/clear_files', methods=['POST'])
def clear_files():
    try:
        for file_path in glob.glob(os.path.join(UPLOAD_FOLDER, '*')):
            try:
                os.remove(file_path)
            except Exception as e:
                return jsonify({'error': f'Error deleting file {file_path}: {e}'}), 500
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@main.route('/')
def index():
    return render_template('index.html')

@main.route('/page2')
def page2():
    return render_template('page2.html')

@main.route('/modules')
def modules():
    # Clear the 'files_saved_here' directory when the modules page is loaded
    clear_files()
    files = UploadedFile.query.all()
    image_urls = [url_for('static', filename=f'images/display/{os.path.splitext(file.filename)[0]}.png') for file in files]
    return render_template('modules.html', image_urls=image_urls)

@main.route('/upload', methods=['POST'])
def upload():
    if 'files' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    files = request.files.getlist('files')

    # Clear existing file records in the database
    UploadedFile.query.delete()
    db.session.commit()

    saved_files = []
    for file in files:
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        filename = file.filename
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        # Save file record to the database
        uploaded_file = UploadedFile(filename=filename)
        db.session.add(uploaded_file)

        saved_files.append(filename)
    
    db.session.commit()

    return jsonify({'files': saved_files}), 200


@main.route('/remove_file', methods=['POST'])
def remove_file():
    data = request.get_json()
    filename = data.get('filename')
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        if os.path.exists(file_path):
            os.remove(file_path)

            # Remove file record from the database
            UploadedFile.query.filter_by(filename=filename).delete()
            db.session.commit()

            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@main.route('/check_files', methods=['GET'])
def check_files():
    directory = UPLOAD_FOLDER
    if not os.listdir(directory):
        return jsonify({'error': 'No images have been uploaded to analyze.'}), 400
    return jsonify({'message': 'Files are present.'}), 200

@main.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    BB_size = data.get('BB_size')
    lowdensity = data.get('lowdensity')
    tolerance = data.get('tolerance')

    directory = UPLOAD_FOLDER
    analyzed_images_dir = 'app/static/images/analyzedpngs'

    try:
        # Check if the directory is empty
        if not os.listdir(directory):
            raise ValueError("No images have been uploaded to analyze.")

        # Clear the analyzed images directory
        if os.path.exists(analyzed_images_dir):
            for file in glob.glob(os.path.join(analyzed_images_dir, '*')):
                os.remove(file)
        else:
            os.makedirs(analyzed_images_dir)


        wl = WinstonLutz(directory)
        wl.analyze(bb_size_mm=BB_size, low_density_bb=lowdensity)
        results = wl.results_data(as_dict=True)
        results = {k: f"{v:.2f}" if isinstance(v, (int, float)) else v for k, v in results.items()}

        gantry_dict = {}
        collimator_dict = {}
        table_dict = {}
        caxtobb_dict = {}

        # Tolerance for considering a value as 0 degrees
        tolerance = 1.0

        keyed_image_details = results["keyed_image_details"]

        for key in keyed_image_details.keys():
            gantry_value = float(key.split('G')[1].split('B')[0])
            collimator_value = float(key.split('B')[1].split('P')[0])
            table_value = float(key.split('P')[1])
    
            # Round values
            gantry_value = round(gantry_value)
            collimator_value = round(collimator_value)
            table_value = round(table_value)

            # Handle gantry value close to 0 or 360 degrees
            if abs(gantry_value - 360) < tolerance or abs(gantry_value) < tolerance:
                gantry_value = 0

            # Handle collimator value close to 0 or 360 degrees
            if abs(collimator_value - 360) < tolerance or abs(collimator_value) < tolerance:
                collimator_value = 0

            # Handle table value close to 0 or 360 degrees
            if abs(table_value - 360) < tolerance or abs(table_value) < tolerance:
                table_value = 0

            # Assign values to dictionaries
            gantry_dict[key] = gantry_value
            collimator_dict[key] = collimator_value
            table_dict[key] = table_value

        # Iterate through the keyed_image_details dictionary
        for i, key in enumerate(keyed_image_details.keys(), start=1):
            image_key = f'image{i}'
            caxtobb_dict[image_key] = round(keyed_image_details[key]['cax2bb_distance'], 2)
        
        # Create analyzed images and temporarily save them to static/images/analyzedjpgs directory
        for i in range(len(wl.images)):
            wl.images[i].save_plot(os.path.join(analyzed_images_dir, f'image{i + 1}.png'))


        return jsonify({
            'results': results,
            'gantry_dict': gantry_dict,
            'collimator_dict': collimator_dict,
            'table_dict': table_dict,
            'caxtobb_dict': caxtobb_dict,
            'key_mapping': {f'image{i}': key for i, key in enumerate(keyed_image_details.keys(), start=1)}
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500