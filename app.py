import os
import re
import uuid
import shutil
import zipfile
import subprocess
from pathlib import Path
from flask import Flask, request, send_file, render_template_string, jsonify

app = Flask(__name__)
BASE = Path("/tmp/fruti-clips")
BASE.mkdir(parents=True, exist_ok=True)
MAX_VIDEO_SECONDS = 7200

PAGE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRUTI CLIPS AI</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101322;color:#fff;font-family:Arial,sans-serif}
main{max-width:760px;margin:40px auto;padding:28px;background:#1b2034;border-radius:18px}
h1{color:#8b7cff;margin:0 0 8px;font-size:34px}p{color:#c8cbe0;line-height:1.5}
label{display:block;margin:18px 0 7px;font-weight:bold}
input,select{width:100%;padding:14px;border:1px solid #444b68;border-radius:10px;background:#111629;color:white;font-size:16px}
button{margin-top:24px;width:100%;padding:15px;border:0;border-radius:10px;background:#7865ff;color:white;font-weight:bold;font-size:17px;cursor:pointer}
small{color:#aeb3cc}.note{background:#282d45;padding:12px;border-radius:10px;margin-top:18px}
</style></head>
<body><main>
<h1>FRUTI CLIPS AI</h1>
<p>Convierte un video en clips verticales para TikTok, Reels y Shorts.</p>
<form method="post" action="/create">
<label>Enlace del video de YouTube</label>
<input name="url" type="url" placeholder="Pega aquí el enlace de YouTube" required>
<label>Duración de cada clip</label>
<select name="duration"><option value="30">30 segundos</option><option value="60">1 minuto</option><option value="90" selected>1 minuto y 30 segundos</option></select>
<label>Cantidad de clips</label>
<select name="count"><option>5</option><option>10</option><option>20</option></select>
<button type="submit">Crear mis clips</button>
</form>
<div class="note"><small>Los clips se generan en formato vertical 9:16. Utiliza videos propios o para los que tengas permiso. El procesamiento puede tardar y está sujeto a los límites del servidor.</small></div>
</main></body></html>
"""

def run(cmd, timeout=1800):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "Error ejecutando el proceso")[-2500:])
    return result

def get_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(r.stdout.strip())

@app.get("/")
def home():
    return render_template_string(PAGE)

@app.post("/create")
def create():
    url = request.form.get("url", "").strip()
    if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", url):
        return "Enlace de YouTube no válido.", 400
    try:
        duration = int(request.form.get("duration", "90"))
        count = int(request.form.get("count", "5"))
        if duration not in (30, 60, 90) or count not in (5, 10, 20):
            return "Selecciona una duración y cantidad permitidas.", 400

        job = BASE / uuid.uuid4().hex
        job.mkdir(parents=True, exist_ok=True)
        video = job / "source.mp4"
        run(["yt-dlp", "--no-playlist", "-f", "bv*[height<=1080]+ba/b[height<=1080]",
             "--merge-output-format", "mp4", "-o", str(video), url], timeout=1800)
        if not video.exists():
            candidates = list(job.glob("source.*"))
            if not candidates:
                raise RuntimeError("No se pudo descargar el video.")
            video = candidates[0]

        total = get_duration(video)
        if total < duration:
            raise RuntimeError("El video es más corto que la duración elegida.")
        if total > MAX_VIDEO_SECONDS:
            raise RuntimeError("Por ahora se aceptan videos de hasta 2 horas.")

        outdir = job / "clips"
        outdir.mkdir()
        usable = total - duration
        for i in range(count):
            start = (usable * i / max(count - 1, 1))
            output = outdir / f"FRUTI_CLIP_{i+1:02d}.mp4"
            run(["ffmpeg", "-y", "-ss", str(start), "-i", str(video),
                 "-t", str(duration), "-vf",
                 "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                 "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                 str(output)], timeout=1200)
        archive = job / "FRUTI_CLIPS.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for clip in sorted(outdir.glob("*.mp4")):
                z.write(clip, clip.name)
        return send_file(archive, as_attachment=True, download_name="FRUTI_CLIPS.zip")
    except subprocess.TimeoutExpired:
        return "El procesamiento tardó demasiado. Prueba con un video más corto.", 504
    except Exception as e:
        return f"No se pudieron crear los clips: {str(e)}", 500

@app.get("/health")
def health():
    return jsonify(status="ok")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
