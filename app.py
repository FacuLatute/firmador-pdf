import hashlib
import io
import os
import tempfile

from flask import Flask, jsonify, request, send_file
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Firmador de PDF</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #f6f7f9;
    color: #1f2430;
    min-height: 100vh;
    padding: 32px 16px;
  }
  .container {
    max-width: 720px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 14px;
    box-shadow: 0 6px 24px rgba(20, 24, 40, 0.06), 0 1px 3px rgba(20, 24, 40, 0.04);
    padding: 32px;
  }
  h1 { font-size: 1.6rem; margin: 0 0 4px; }
  .subtitle { color: #6b7280; margin: 0 0 24px; font-size: 0.95rem; }
  .dropzone {
    border: 2px dashed #cbd5e1;
    border-radius: 12px;
    padding: 32px 16px;
    text-align: center;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    background: #fafbfc;
  }
  .dropzone:hover, .dropzone.drag {
    border-color: #2563eb;
    background: #eff6ff;
  }
  .dropzone p { margin: 6px 0; color: #4b5563; }
  .dropzone .hint { font-size: 0.85rem; color: #9ca3af; }
  .file-name {
    margin-top: 12px;
    font-size: 0.9rem;
    color: #0f172a;
    font-weight: 600;
    word-break: break-all;
  }
  .section-title {
    margin: 28px 0 12px;
    font-size: 1.05rem;
    font-weight: 600;
  }
  .signer-row {
    display: grid;
    grid-template-columns: 1fr 1fr auto;
    gap: 8px;
    margin-bottom: 8px;
  }
  input[type="text"] {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    font-size: 0.95rem;
    font-family: inherit;
    background: #fff;
  }
  input[type="text"]:focus {
    outline: none;
    border-color: #2563eb;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
  }
  button {
    font-family: inherit;
    font-size: 0.95rem;
    border: none;
    cursor: pointer;
    border-radius: 8px;
    padding: 10px 14px;
    transition: background 0.15s, opacity 0.15s;
  }
  .btn-remove {
    background: #fee2e2;
    color: #b91c1c;
    padding: 10px 12px;
  }
  .btn-remove:hover { background: #fecaca; }
  .btn-add {
    background: #eef2ff;
    color: #3730a3;
    margin-top: 4px;
  }
  .btn-add:hover { background: #e0e7ff; }
  .btn-primary {
    background: #2563eb;
    color: #fff;
    width: 100%;
    padding: 14px;
    font-size: 1rem;
    font-weight: 600;
    margin-top: 24px;
  }
  .btn-primary:hover { background: #1d4ed8; }
  .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
  .error {
    margin-top: 16px;
    padding: 12px 14px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
    border-radius: 8px;
    font-size: 0.9rem;
    display: none;
  }
  .error.show { display: block; }
  .loading {
    display: none;
    text-align: center;
    margin-top: 16px;
    color: #4b5563;
    font-size: 0.9rem;
  }
  .loading.show { display: block; }
  .spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid #cbd5e1;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (max-width: 540px) {
    .container { padding: 20px; }
    .signer-row { grid-template-columns: 1fr; }
    .btn-remove { width: 100%; }
  }
</style>
</head>
<body>
  <div class="container">
    <h1>Firmador de PDF</h1>
    <p class="subtitle">Subí un PDF, cargá los firmantes y descargá el documento firmado.</p>

    <form id="form">
      <div id="dropzone" class="dropzone">
        <input type="file" id="pdfInput" accept="application/pdf" hidden>
        <p><strong>Arrastrá un PDF aquí</strong> o hacé clic para seleccionar</p>
        <p class="hint">Formato aceptado: PDF</p>
        <div id="fileName" class="file-name"></div>
      </div>

      <div class="section-title">Firmantes</div>
      <div id="signers"></div>
      <button type="button" class="btn-add" id="addSigner">+ Agregar firmante</button>

      <button type="submit" class="btn-primary" id="submitBtn">Firmar PDF</button>

      <div id="error" class="error"></div>
      <div id="loading" class="loading"><span class="spinner"></span>Procesando documento...</div>
    </form>
  </div>

<script>
(function(){
  const dropzone = document.getElementById('dropzone');
  const pdfInput = document.getElementById('pdfInput');
  const fileName = document.getElementById('fileName');
  const signersEl = document.getElementById('signers');
  const addBtn = document.getElementById('addSigner');
  const form = document.getElementById('form');
  const errorEl = document.getElementById('error');
  const loadingEl = document.getElementById('loading');
  const submitBtn = document.getElementById('submitBtn');

  let selectedFile = null;

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.add('show');
  }
  function clearError() {
    errorEl.classList.remove('show');
    errorEl.textContent = '';
  }

  function addSignerRow(name, dni) {
    const row = document.createElement('div');
    row.className = 'signer-row';
    row.innerHTML = `
      <input type="text" class="signer-name" placeholder="Nombre y apellido" value="${name || ''}">
      <input type="text" class="signer-dni" placeholder="DNI" value="${dni || ''}">
      <button type="button" class="btn-remove" title="Eliminar">✕</button>
    `;
    row.querySelector('.btn-remove').addEventListener('click', () => {
      row.remove();
    });
    signersEl.appendChild(row);
  }

  addSignerRow();
  addBtn.addEventListener('click', () => addSignerRow());

  dropzone.addEventListener('click', () => pdfInput.click());
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  });
  pdfInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) handleFile(e.target.files[0]);
  });

  function handleFile(file) {
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      showError('Solo se aceptan archivos PDF.');
      return;
    }
    clearError();
    selectedFile = file;
    fileName.textContent = file.name;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();

    if (!selectedFile) {
      showError('Seleccioná un archivo PDF.');
      return;
    }

    const rows = signersEl.querySelectorAll('.signer-row');
    const signers = [];
    rows.forEach(row => {
      const name = row.querySelector('.signer-name').value.trim();
      const dni = row.querySelector('.signer-dni').value.trim();
      if (name || dni) signers.push({ name, dni });
    });

    if (signers.length === 0) {
      showError('Agregá al menos un firmante con nombre y DNI.');
      return;
    }
    for (const s of signers) {
      if (!s.name || !s.dni) {
        showError('Todos los firmantes deben tener nombre y DNI.');
        return;
      }
    }

    const fd = new FormData();
    fd.append('pdf', selectedFile);
    fd.append('signers', JSON.stringify(signers));

    submitBtn.disabled = true;
    loadingEl.classList.add('show');

    try {
      const resp = await fetch('/sign', { method: 'POST', body: fd });
      if (!resp.ok) {
        let msg = 'Ocurrió un error al procesar el PDF.';
        try { const j = await resp.json(); if (j.error) msg = j.error; } catch (_) {}
        showError(msg);
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const base = selectedFile.name.replace(/\.pdf$/i, '');
      a.href = url;
      a.download = base + '_firmado.pdf';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError('No se pudo conectar con el servidor.');
    } finally {
      submitBtn.disabled = false;
      loadingEl.classList.remove('show');
    }
  });
})();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return INDEX_HTML


def _build_stamp(page_width, page_height, signers, file_hash):
    """Build an overlay PDF page with the signature block at the bottom."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    margin = 24
    padding = 10
    col_gap = 8
    name_size = 10
    dni_size = 9
    label_size = 7
    hash_size = 7
    line_gap = 3

    col_height = (
        padding
        + name_size
        + line_gap
        + dni_size
        + line_gap
        + label_size
        + padding
    )
    hash_area = line_gap + hash_size + padding
    block_height = col_height + hash_area
    block_width = page_width - 2 * margin
    block_x = margin
    block_y = margin

    # Background
    c.setFillColor(HexColor("#f3f4f6"))
    c.setStrokeColor(HexColor("#d1d5db"))
    c.setLineWidth(0.5)
    c.rect(block_x, block_y, block_width, block_height, fill=1, stroke=1)

    # Signer columns
    n = max(1, len(signers))
    total_gap = col_gap * (n - 1)
    col_width = (block_width - 2 * padding - total_gap) / n
    cols_top = block_y + block_height - padding
    cols_bottom = block_y + hash_area

    for i, s in enumerate(signers):
        cx = block_x + padding + i * (col_width + col_gap)
        center_x = cx + col_width / 2

        # Separator between columns
        if i > 0:
            sep_x = cx - col_gap / 2
            c.setStrokeColor(HexColor("#e5e7eb"))
            c.setLineWidth(0.4)
            c.line(sep_x, cols_bottom + 2, sep_x, cols_top - 2)

        c.setFillColor(HexColor("#111827"))
        c.setFont("Helvetica-Bold", name_size)
        y = cols_top - name_size
        c.drawCentredString(center_x, y, _truncate(c, s["name"], "Helvetica-Bold", name_size, col_width))

        c.setFont("Helvetica", dni_size)
        y -= line_gap + dni_size
        c.setFillColor(HexColor("#374151"))
        c.drawCentredString(center_x, y, _truncate(c, "DNI: " + s["dni"], "Helvetica", dni_size, col_width))

        c.setFont("Helvetica-Oblique", label_size)
        y -= line_gap + label_size
        c.setFillColor(HexColor("#6b7280"))
        c.drawCentredString(center_x, y, "Firma Electrónica — Ley 25.506")

    # Separator above hash
    c.setStrokeColor(HexColor("#e5e7eb"))
    c.setLineWidth(0.4)
    c.line(block_x + padding, cols_bottom, block_x + block_width - padding, cols_bottom)

    # Hash centered below
    c.setFont("Courier", hash_size)
    c.setFillColor(HexColor("#6b7280"))
    hash_y = block_y + padding
    c.drawCentredString(block_x + block_width / 2, hash_y, "SHA-256: " + file_hash)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _truncate(c, text, font, size, max_width):
    if c.stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    while text and c.stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return text + ellipsis


@app.route("/sign", methods=["POST"])
def sign():
    import json

    if "pdf" not in request.files:
        return jsonify({"error": "No se envió ningún archivo PDF."}), 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename:
        return jsonify({"error": "Archivo PDF inválido."}), 400

    try:
        signers = json.loads(request.form.get("signers", "[]"))
    except json.JSONDecodeError:
        return jsonify({"error": "Datos de firmantes inválidos."}), 400

    signers = [
        {"name": (s.get("name") or "").strip(), "dni": (s.get("dni") or "").strip()}
        for s in signers
        if isinstance(s, dict)
    ]
    signers = [s for s in signers if s["name"] and s["dni"]]

    if not signers:
        return jsonify({"error": "Agregá al menos un firmante con nombre y DNI."}), 400

    with tempfile.TemporaryFile() as src:
        pdf_file.save(src)
        src.seek(0)
        data = src.read()

    file_hash = hashlib.sha256(data).hexdigest()

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return jsonify({"error": "No se pudo leer el PDF."}), 400

    writer = PdfWriter()

    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        stamp_buf = _build_stamp(width, height, signers, file_hash)
        stamp_reader = PdfReader(stamp_buf)
        page.merge_page(stamp_reader.pages[0])
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)

    original_name = os.path.splitext(os.path.basename(pdf_file.filename))[0]
    download_name = f"{original_name}_firmado.pdf"

    return send_file(
        out,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
