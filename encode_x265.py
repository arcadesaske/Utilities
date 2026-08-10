#!/usr/bin/env python3
# encode_x265.command
# Avvia nella directory dei file da encodare

import json
import subprocess
import sys
import os
import signal
import logging
import threading
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# ─── Configurazione ───────────────────────────────────────────────────────────

LANG_ORDER  = ["eng", "fra", "deu", "ita"]
PRESET      = "medium"
EXTENSIONS  = {".mkv", ".mp4", ".avi", ".m4v", ".ts"}
CRF         = 20  # default

CODEC_NAMES = {
    "eac3":      "E-AC3",
    "ac3":       "AC3",
    "dts":       "DTS",
    "truehd":    "TrueHD",
    "aac":       "AAC",
    "flac":      "FLAC",
    "mp3":       "MP3",
    "opus":      "Opus",
    "vorbis":    "Vorbis",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM",
}

CHANNEL_LABELS = {
    "mono":        "1.0",
    "stereo":      "2.0",
    "2.1":         "2.1",
    "3.0":         "3.0",
    "3.0(back)":   "3.0",
    "quad":        "4.0",
    "4.0":         "4.0",
    "5.0":         "5.0",
    "5.1":         "5.1",
    "5.1(side)":   "5.1",
    "6.1":         "6.1",
    "7.1":         "7.1",
    "7.1(wide)":   "7.1",
    "hexagonal":   "6.0",
    "octagonal":   "8.0",
}

# ─── Stato globale per interrupt ──────────────────────────────────────────────

current_process = None
interrupted     = False

def handle_sigint(sig, frame):
    global interrupted, current_process
    interrupted = True
    log_and_print("\n⚠️  Interruzione richiesta — attendo fine encoding corrente...")
    if current_process and current_process.poll() is None:
        current_process.terminate()

signal.signal(signal.SIGINT, handle_sigint)

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = None

def setup_logging(output_dir):
    global logger
    log_path = output_dir / "encode_results.log"
    logger = logging.getLogger("encoder")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8", mode='a')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(fh)
    print(f"📝 Log: {log_path}\n")


def log_and_print(msg):
    tqdm.write(msg)
    if logger:
        logger.info(msg)

# ─── Probe ────────────────────────────────────────────────────────────────────

def probe(path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", str(path)
    ], capture_output=True, text=True)
    return json.loads(result.stdout).get("streams", [])

def get_total_frames(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(path)
        ],
        capture_output=True,
        text=True
    )
    streams = json.loads(result.stdout).get("streams", [])
    for s in streams:
        if s.get("codec_type") != "video":
            continue
        if s.get("nb_frames"):
            return int(s["nb_frames"])
        tags = s.get("tags", {})
        if tags.get("NUMBER_OF_FRAMES"):
            return int(tags["NUMBER_OF_FRAMES"])
        duration = s.get("duration")
        if duration:
            fps_str = s.get("r_frame_rate", "25/1")
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
            return round(float(duration) * fps)
    return None

# ─── Nomi tracce ──────────────────────────────────────────────────────────────

def audio_track_name(stream, codec_override=None):
    codec = codec_override or CODEC_NAMES.get(
        stream.get("codec_name", "").lower(),
        stream.get("codec_name", "?").upper()
    )
    layout   = stream.get("channel_layout", "")
    channels = CHANNEL_LABELS.get(layout)
    if not channels:
        n = stream.get("channels", 0)
        channels = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}.get(n, f"{n}ch")
    lang = stream.get("tags", {}).get("language", "").lower()
    name = f"{codec} {channels}"
    if lang == "ita":
        name += " iTA"
    return name


def subtitle_track_name(stream):
    lang  = stream.get("tags", {}).get("language", "").lower()
    title = stream.get("tags", {}).get("title", "").upper()
    forced_by_disposition = int(stream.get("disposition", {}).get("forced", 0))
    forced_by_title       = "FORCED" in title
    forced                = forced_by_disposition or forced_by_title
    set_forced            = forced_by_title and not forced_by_disposition
    if lang == "ita":
        name = "FORZATI" if forced else "REGOLARI"
    elif lang == "eng":
        name = "FORCED"  if forced else "REGULAR"
    else:
        name = lang
    return name, set_forced


def is_sdh(stream):
    by_disposition = int(stream.get("disposition", {}).get("hearing_impaired", 0))
    title          = stream.get("tags", {}).get("title", "").upper()
    return bool(by_disposition or "SDH" in title)

# ─── Filtri ───────────────────────────────────────────────────────────────────

def filter_audio(streams):
    candidate_streams = [s for s in streams if s.get("codec_type") == "audio"]

    by_lang = {}
    for s in candidate_streams:
        lang = s.get("tags", {}).get("language", "und")
        by_lang.setdefault(lang, []).append(s)

    result    = []
    discarded = []

    for lang, tracks in by_lang.items():
        eac3   = [s for s in tracks if s.get("codec_name", "").lower() == "eac3"]
        ac3    = [s for s in tracks if s.get("codec_name", "").lower() == "ac3"]
        others = [s for s in tracks if s.get("codec_name", "").lower() not in ("eac3", "ac3")]

        if eac3:
            for s in eac3:
                result.append((s, {"mode": "copy"}))
            for s in ac3 + others:
                discarded.append(s)
        elif others and ac3:
            for s in others:
                src_kbps = int(s.get("bit_rate", 0)) // 1000
                if src_kbps == 0:
                    src_kbps = 768
                target_kbps = min(src_kbps, 768)
                result.append((s, {"mode": "encode", "bitrate": target_kbps}))
            for s in ac3:
                discarded.append(s)
        elif ac3:
            for s in ac3:
                result.append((s, {"mode": "copy"}))
        else:
            for s in others:
                result.append((s, {"mode": "copy"}))

    lang_priority = {lang: i for i, lang in enumerate(LANG_ORDER)}
    order = {s["index"]: i for i, s in enumerate(candidate_streams)}
    result.sort(key=lambda x: (
        lang_priority.get(x[0].get("tags", {}).get("language", "und").lower(), 99),
        order.get(x[0]["index"], 999)
    ))

    return result, discarded


def filter_subtitles(streams):
    ALLOWED_SUB_CODECS = {"subrip", "ass", "ssa", "webvtt"}

    sub_streams = [
        s for s in streams
        if s.get("codec_type") == "subtitle"
        and s.get("codec_name", "").lower() in ALLOWED_SUB_CODECS
    ]
    discarded = [
        s for s in streams
        if s.get("codec_type") == "subtitle"
        and s.get("codec_name", "").lower() not in ALLOWED_SUB_CODECS
    ]
    for s in discarded:
        lang  = s.get("tags", {}).get("language", "?")
        codec = s.get("codec_name", "?")
        log_and_print(f"   🚫 Sub scartato [{lang}] codec non ammesso: {codec}")

    by_lang = {}
    for s in sub_streams:
        lang = s.get("tags", {}).get("language", "und")
        by_lang.setdefault(lang, []).append(s)

    result = []
    for lang, tracks in by_lang.items():
        sdh_tracks     = [s for s in tracks if is_sdh(s)]
        regular_tracks = [s for s in tracks if not is_sdh(s)]
        if regular_tracks:
            for s in regular_tracks:
                result.append((s, False))
        else:
            for s in sdh_tracks:
                result.append((s, True))

    order = {s["index"]: i for i, s in enumerate(sub_streams)}
    result.sort(key=lambda x: order.get(x[0]["index"], 999))
    return result

# ─── Encode ───────────────────────────────────────────────────────────────────

def encode(input_path, output_dir, file_bar):
    global current_process, interrupted

    if interrupted:
        return

    streams     = probe(input_path)
    output_path = output_dir / (input_path.stem + ".mkv")
    start_time  = datetime.now()

    log_and_print(f"\n{'━'*50}")
    log_and_print(f"▶  {input_path.name}")
    log_and_print(f"   Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Map video ─────────────────────────────────────────────────────────────
    cmd = ["ffmpeg", "-hwaccel", "videotoolbox", "-i", str(input_path), "-map", "0:V"]
    # ── Map audio ─────────────────────────────────────────────────────────────
    filtered_audio, discarded_audio = filter_audio(streams)

    audio_meta = []
    for i, (s, action) in enumerate(filtered_audio):
        cmd += ["-map", f"0:{s['index']}"]
        lang = s.get("tags", {}).get("language", "?")
        if action["mode"] == "copy":
            name = audio_track_name(s)
            audio_meta += [f"-metadata:s:a:{i}", f"title={name}"]
            audio_meta += [f"-c:a:{i}", "copy"]
            log_and_print(f"   🎵 Audio {i}: {name}  [{lang}]")
        elif action["mode"] == "encode":
            name    = audio_track_name(s, codec_override="E-AC3")
            bitrate = action["bitrate"]
            audio_meta += [f"-metadata:s:a:{i}", f"title={name}"]
            audio_meta += [f"-c:a:{i}", "eac3", f"-b:a:{i}", f"{bitrate}k"]
            src_codec = CODEC_NAMES.get(s.get("codec_name", "").lower(), s.get("codec_name", "?").upper())
            log_and_print(f"   🎵 Audio {i}: {name}  [{lang}]  [{src_codec}→E-AC3 {bitrate}k]")

    for s in discarded_audio:
        lang  = s.get("tags", {}).get("language", "?")
        codec = CODEC_NAMES.get(s.get("codec_name", "").lower(), s.get("codec_name", "?").upper())
        log_and_print(f"   🚫 Audio scartato [{lang}] {codec}")

    # ── Map subtitle ──────────────────────────────────────────────────────────
    filtered_subs = filter_subtitles(streams)
    sub_meta      = []
    for i, (s, promoted) in enumerate(filtered_subs):
        cmd += ["-map", f"0:{s['index']}"]
        name, set_forced = subtitle_track_name(s)
        sub_meta += [f"-metadata:s:s:{i}", f"title={name}"]
        if set_forced:
            sub_meta += [f"-disposition:s:{i}", "forced"]
        lang   = s.get("tags", {}).get("language", "?")
        labels = []
        if promoted:
            labels.append("SDH→REGULAR")
        if set_forced:
            labels.append("forced da titolo→disposition")
        label_str = f"  [{', '.join(labels)}]" if labels else ""
        log_and_print(f"   💬 Sub  {i}: {name}  [{lang}]{label_str}")

    # ── Chapters + metadata ───────────────────────────────────────────────────
    cmd += ["-map_chapters", "0", "-map_metadata", "0"]

    # ── Codec ─────────────────────────────────────────────────────────────────
    log_and_print(f"   🎬 CRF: {CRF}  |  Preset: {PRESET}")
    cmd += [
        "-c:v", "libx265",
        "-crf", str(CRF),
        "-preset", PRESET,
        "-pix_fmt", "yuv420p10le",
        "-tag:v", "hvc1",
        "-x265-params", "log-level=error",
        "-c:s", "copy",
    ]

    cmd += audio_meta + sub_meta
    cmd += ["-progress", "pipe:1", "-nostats", "-y", str(output_path)]

    # ── Esecuzione con progress bar ───────────────────────────────────────────
    total_frames = get_total_frames(input_path)

    current_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Drain stderr in background per evitare che il buffer blocchi il processo
    stderr_lines = []
    def drain_stderr():
        for line in current_process.stderr:
            stderr_lines.append(line)
    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    bar = tqdm(
        total=total_frames,
        unit="f",
        desc="  Encoding",
        position=1,
        bar_format="{l_bar}{bar}| [ETA: {remaining}, {rate_fmt}]",
        colour="green",
        leave=True,
        dynamic_ncols=True
    )

    current = 0
    for line in current_process.stdout:
        if interrupted:
            break
        if line.startswith("frame="):
            try:
                frame = int(line.strip().split("=")[1])
                delta = frame - current
                if delta > 0:
                    bar.update(delta)
                    current = frame
            except ValueError:
                pass

    current_process.wait()
    stderr_thread.join()
    bar.close()

    end_time    = datetime.now()
    elapsed     = end_time - start_time
    elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"

    if interrupted:
        if output_path.exists():
            output_path.unlink()
        log_and_print(f"  ⚠️  Interrotto: {input_path.name} — file parziale rimosso")
    elif current_process.returncode == 0:
        size = output_path.stat().st_size / (1024 ** 3)
        log_and_print(f"  ✅ OK: {output_path.name}  |  Durata: {elapsed_str}  |  Dimensione: {size:.2f} GiB")
    else:
        stderr_out = "".join(stderr_lines)
        log_and_print(f"  ❌ ERRORE: {input_path.name}  |  Durata: {elapsed_str}")
        log_and_print(f"  ffmpeg: {stderr_out[-500:]}")

    current_process = None
    file_bar.update(1)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global CRF

    input_dir  = Path(__file__).parent
    output_dir = Path(__file__).parent.parent.parent / "Encoded"
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(output_dir)

    try:
        CRF = int(input("⚙️  CRF (default 20): ") or 20)
    except ValueError:
        print("❌ Valore non valido, uso default 20")
        CRF = 19
    try:
        choice = int(input("⚙️  PRESET (default medium): \n0. medium \n1. superfast") or 0)
        PRESET = "medium" if choice == 0 else "superfast"
    except ValueError:
        print("❌ Valore non valido, uso default medium")
        PRESET = "medium"
            
    files = sorted([f for f in input_dir.iterdir() if f.suffix.lower() in EXTENSIONS])

    if not files:
        print(f"⚠️  Nessun file video trovato in: {input_dir}")
        input("Premi Invio per chiudere...")
        sys.exit(0)

    log_and_print(f"📂 {len(files)} file trovati in: {input_dir}")
    log_and_print(f"📁 Output: {output_dir}")
    log_and_print(f"⚙️  CRF: {CRF}  |  Preset: {PRESET}")

    file_bar = tqdm(
        total=len(files),
        desc="Total files",
        unit="file",
        position=0,
        leave=True,
        bar_format="{l_bar}{bar}| {n}/{total}"
    )

    for f in files:
        if interrupted:
            break
        encode(f, output_dir, file_bar)

    file_bar.close()

    log_and_print(f"\n{'━'*50}")
    if interrupted:
        log_and_print("🛑 Encoding interrotto dall'utente.")
    else:
        log_and_print("🏁 Completato.")
    log_and_print(f"📁 File in: {output_dir}")
    input("Premi Invio per chiudere...")


if __name__ == "__main__":
    main()