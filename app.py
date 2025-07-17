# app.py (Final Version for Hosting)

import os
import re
import json
import io
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import fitz  # PyMuPDF
import PyPDF2
from PIL import Image
import pytesseract

# --- OCR CONFIGURATION ---
# If you are on Windows and installed Tesseract in a custom location, you may
# need to uncomment and set the path below. On Render, this is not needed.
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


# --- GENERAL CONFIGURATION ---
PDF_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
INDEX_FILE = 'pdf_index.json'
ROLL_NUMBER_REGEX = re.compile(r'(23|24)(BC|BA)\d{3}', re.IGNORECASE)

# --- INITIALIZE FLASK APP for Production ---
# The 'static_folder' is explicitly set to the root to serve index.html, style.css, etc.
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- CORE LOGIC ---

def create_index():
    """
    Reads all PDF files using a TRIPLE ENGINE approach:
    1. PyPDF2 for basic extraction.
    2. PyMuPDF for advanced direct text extraction.
    3. Tesseract OCR for scanned images.
    """
    print("Starting PDF indexing process with TRIPLE ENGINE (PyPDF2 + PyMuPDF + OCR)...")
    if not os.path.exists(PDF_DIRECTORY):
        print(f"Error: The directory '{PDF_DIRECTORY}' was not found.")
        return None

    pdf_files = [f for f in os.listdir(PDF_DIRECTORY) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"Warning: No PDF files found in '{PDF_DIRECTORY}'.")
        return {}

    index = {}
    total_files = len(pdf_files)

    for i, filename in enumerate(pdf_files):
        print(f"Processing file {i+1}/{total_files}: {filename}...")
        try:
            filepath = os.path.join(PDF_DIRECTORY, filename)
            # Open file with both libraries
            with fitz.open(filepath) as fitz_doc, open(filepath, 'rb') as pdf_file_obj:
                pypdf2_reader = PyPDF2.PdfReader(pdf_file_obj)
                
                for page_num, fitz_page in enumerate(fitz_doc, start=1):
                    # --- TRIPLE ENGINE EXTRACTION ---
                    
                    # Method 1: PyPDF2 extraction
                    text_pypdf2 = ""
                    try:
                        if page_num <= len(pypdf2_reader.pages):
                            pypdf2_page = pypdf2_reader.pages[page_num - 1]
                            text_pypdf2 = pypdf2_page.extract_text() or ""
                    except Exception as pypdf2_error:
                        print(f"  - PyPDF2 failed on page {page_num} of {filename}: {pypdf2_error}")

                    # Method 2: PyMuPDF extraction
                    text_pymupdf = fitz_page.get_text() or ""

                    # Method 3: Tesseract OCR
                    text_ocr = ""
                    try:
                        pix = fitz_page.get_pixmap(dpi=300)
                        img_data = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_data))
                        text_ocr = pytesseract.image_to_string(img) or ""
                    except Exception as ocr_error:
                        print(f"  - OCR failed on page {page_num} of {filename}: {ocr_error}")

                    # Combine text from all three methods
                    combined_text = f"{text_pypdf2}\n{text_pymupdf}\n{text_ocr}"
                    
                    if not combined_text.strip():
                        continue

                    found_on_page = set()
                    full_matches = ROLL_NUMBER_REGEX.finditer(combined_text)
                    for match in full_matches:
                        found_on_page.add(match.group(0).upper())
                    
                    for roll_number in found_on_page:
                        print(f"  -> Found '{roll_number}' in '{filename}' on page {page_num}")
                        if roll_number not in index:
                            index[roll_number] = []
                        location = {'doc': filename, 'page': page_num}
                        if location not in index[roll_number]:
                            index[roll_number].append(location)

        except Exception as e:
            print(f"Error processing file {filename}: {e}")

    with open(INDEX_FILE, 'w') as f:
        json.dump(index, f, indent=2)
    
    print(f"Indexing complete. Found {len(index)} unique roll numbers.")
    print(f"Index saved to {INDEX_FILE}")
    return index

def load_index():
    """Loads the index, creating it if it doesn't exist."""
    if os.path.exists(INDEX_FILE):
        print(f"Loading existing index from {INDEX_FILE}...")
        with open(INDEX_FILE, 'r') as f:
            return json.load(f)
    else:
        print("No index file found. Creating a new one.")
        return create_index()

# --- FLASK ROUTES ---

@app.route('/')
def serve_index_page():
    """Serves the main index.html file."""
    return send_from_directory('.', 'index.html')

@app.route('/search')
def search_roll_number():
    """Handles search queries."""
    query = request.args.get('q', '').strip().upper()
    if not query:
        return jsonify({'error': 'A roll number query is required.'}), 400
    results = pdf_index.get(query, [])
    return jsonify({'query': query, 'results': results})

@app.route('/docs/<path:filename>')
def serve_pdf(filename):
    """Serves the PDF documents."""
    return send_from_directory(PDF_DIRECTORY, filename)
    
@app.route('/rebuild_index')
def rebuild_index_endpoint():
    """Allows manually triggering a re-index."""
    global pdf_index
    try:
        if os.path.exists(INDEX_FILE):
            os.remove(INDEX_FILE)
            print(f"Removed old index file: {INDEX_FILE}")
        new_index = create_index()
        if new_index is not None:
            pdf_index = new_index
            return jsonify({"status": "success", "message": "Index rebuilt successfully with Triple Engine."})
        else:
            return jsonify({"status": "error", "message": "Failed to rebuild index."}), 500
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during re-indexing: {e}")
        return jsonify({"status": "error", "message": f"An internal server error occurred. See console for details."}), 500

# --- IMPORTANT: Ensure the index is loaded on startup ---
# This block runs when the application starts on the server.
with app.app_context():
    # Create the 'docs' directory if it doesn't exist. On Render, you will
    # need to find a way to upload your PDFs, like a cloud storage service.
    if not os.path.exists(PDF_DIRECTORY):
        os.makedirs(PDF_DIRECTORY)
        print(f"Created PDF directory at: {PDF_DIRECTORY}")
    
    # Load the index into memory.
    pdf_index = load_index()
    if pdf_index is None:
        print("\nCould not start the server due to an indexing error.")
    else:
        print("\nIndex loaded successfully. Application is ready.")

# Note: The `if __name__ == '__main__':` block is removed.
# The production server (Gunicorn) will run the 'app' object directly.
