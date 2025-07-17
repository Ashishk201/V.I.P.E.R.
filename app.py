# app.py (Final Version with Cloudinary Integration)

import os
import re
import json
import io
import cloudinary
import cloudinary.api
import cloudinary.uploader
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import fitz
import PyPDF2
from PIL import Image
import pytesseract

# --- CONFIGURATION ---
# This is where the app will temporarily store PDFs downloaded from Cloudinary
PDF_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_docs')
INDEX_FILE = 'pdf_index.json'
ROLL_NUMBER_REGEX = re.compile(r'(23|24)(BC|BA)\d{3}', re.IGNORECASE)

# --- INITIALIZE FLASK APP for Production ---
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- CLOUDINARY SETUP ---
# IMPORTANT: These credentials will be set as Environment Variables in Render
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

def download_pdfs_from_cloudinary():
    """
    Connects to Cloudinary, fetches all PDFs, and saves them to the local PDF_DIRECTORY.
    """
    if not os.path.exists(PDF_DIRECTORY):
        os.makedirs(PDF_DIRECTORY)
        print(f"Created temporary PDF directory at: {PDF_DIRECTORY}")

    print("Connecting to Cloudinary to download PDFs...")
    try:
        # Fetch all resources of type 'raw' (for PDFs) in the 'pdfs' folder
        # Note: The free plan might limit the number of results per call.
        # For more than 500 files, you'd need to handle pagination.
        resources = cloudinary.api.resources(
            type="upload",
            resource_type="raw",
            prefix="pdfs/",  # Assumes you created a 'pdfs' folder in Cloudinary
            max_results=500
        )
        
        for resource in resources.get('resources', []):
            file_url = resource['secure_url']
            # The public_id includes the folder path, e.g., 'pdfs/document1.pdf'
            # We just want the filename.
            filename = os.path.basename(resource['public_id'])
            filepath = os.path.join(PDF_DIRECTORY, filename)
            
            print(f"Downloading {filename}...")
            # Use cloudinary's fetch method to get the file content
            response = cloudinary.uploader.upload(file_url, resource_type="raw")
            
            # Since we can't directly download, we upload from URL to get a temp file path
            # A better way is to use requests library for direct download
            import requests
            with requests.get(file_url, stream=True) as r:
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        
        print("All PDFs downloaded successfully from Cloudinary.")
        return True

    except Exception as e:
        print(f"Error connecting to or downloading from Cloudinary: {e}")
        return False

# --- CORE LOGIC (Functions are unchanged, but they now use the downloaded files) ---

def create_index():
    # ... (The body of this function is exactly the same as before)
    print("Starting PDF indexing process...")
    if not os.path.exists(PDF_DIRECTORY): return None
    pdf_files = [f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith('.pdf')]
    if not pdf_files: return {}
    index = {}
    for i, filename in enumerate(pdf_files):
        print(f"Processing file {i+1}/{len(pdf_files)}: {filename}...")
        try:
            filepath = os.path.join(PDF_DIRECTORY, filename)
            with fitz.open(filepath) as fitz_doc, open(filepath, 'rb') as pdf_file_obj:
                pypdf2_reader = PyPDF2.PdfReader(pdf_file_obj)
                for page_num, fitz_page in enumerate(fitz_doc, start=1):
                    text_pypdf2 = pypdf2_reader.pages[page_num - 1].extract_text() or ""
                    text_pymupdf = fitz_page.get_text() or ""
                    pix = fitz_page.get_pixmap(dpi=300)
                    img_data = pix.tobytes("png")
                    img = Image.open(io.BytesIO(img_data))
                    text_ocr = pytesseract.image_to_string(img) or ""
                    combined_text = f"{text_pypdf2}\n{text_pymupdf}\n{text_ocr}"
                    if not combined_text.strip(): continue
                    found_on_page = set(match.group(0).upper() for match in ROLL_NUMBER_REGEX.finditer(combined_text))
                    for roll_number in found_on_page:
                        if roll_number not in index: index[roll_number] = []
                        location = {'doc': filename, 'page': page_num}
                        if location not in index[roll_number]: index[roll_number].append(location)
        except Exception as e:
            print(f"Error processing file {filename}: {e}")
    with open(INDEX_FILE, 'w') as f: json.dump(index, f, indent=2)
    print(f"Indexing complete. Found {len(index)} unique roll numbers.")
    return index


def load_index():
    if os.path.exists(INDEX_FILE):
        print(f"Loading existing index from {INDEX_FILE}...")
        with open(INDEX_FILE, 'r') as f: return json.load(f)
    print("No index file found. Creating a new one.")
    return create_index()

# --- FLASK ROUTES (Unchanged) ---

@app.route('/')
def serve_index_page():
    return send_from_directory('.', 'index.html')

@app.route('/search')
def search_roll_number():
    query = request.args.get('q', '').strip().upper()
    if not query: return jsonify({'error': 'A roll number query is required.'}), 400
    results = pdf_index.get(query, [])
    return jsonify({'query': query, 'results': results})

@app.route('/docs/<path:filename>')
def serve_pdf(filename):
    # This now serves files from the temporary directory
    return send_from_directory(PDF_DIRECTORY, filename)
    
@app.route('/rebuild_index')
def rebuild_index_endpoint():
    global pdf_index
    if os.path.exists(INDEX_FILE): os.remove(INDEX_FILE)
    # Re-download all files before indexing
    download_pdfs_from_cloudinary()
    pdf_index = create_index()
    if pdf_index is not None:
        return jsonify({"status": "success", "message": "Index rebuilt successfully from Cloudinary."})
    return jsonify({"status": "error", "message": "Failed to rebuild index."}), 500

# --- APPLICATION STARTUP ---
with app.app_context():
    # 1. Download all PDFs from Cloudinary
    download_pdfs_from_cloudinary()
    # 2. Load the index (or create it from the downloaded files)
    pdf_index = load_index()
    if pdf_index is None:
        print("\nCould not start the server due to an indexing error.")
    else:
        print("\nIndex loaded successfully. Application is ready.")
